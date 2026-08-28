using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using vcp = HighPrecisionStepperJuggler.OpenCVConstants.VideoCaptureProperties;
using c = HighPrecisionStepperJuggler.Constants;
using UnityEngine;
using UnityEngine.Experimental.Rendering.HDPipeline;
using UnityEngine.Rendering;

namespace HighPrecisionStepperJuggler
{
    public class UVCCameraPlugin : MonoBehaviour
    {
        [SerializeField] private Volume _volume;
        [SerializeField] private ImageProcessingCaptionView _captionView;

        [DllImport("UVCCameraPlugin")]
        private static extern IntPtr getCamera();

        [DllImport("UVCCameraPlugin")]
        private static extern double getCameraProperty(IntPtr camera, int propertyId);

        [DllImport("UVCCameraPlugin")]
        private static extern double setCameraProperty(IntPtr camera, int propertyId, double value);

        [DllImport("UVCCameraPlugin")]
        private static extern void releaseCamera(IntPtr camera);

        [DllImport("UVCCameraPlugin")]
        [return: MarshalAs(UnmanagedType.I1)]
        private static extern bool applyCameraControls(
            double autoExposure,
            double exposure,
            double gain,
            double saturation,
            double contrast,
            double brightness,
            double gamma,
            double[] readback);

        [DllImport("UVCCameraPlugin")]
        [return: MarshalAs(UnmanagedType.I1)]
        private static extern bool getCameraTexture(
            IntPtr camera,
            IntPtr data,
            [MarshalAs(UnmanagedType.I1)] bool executeHT21,
            [MarshalAs(UnmanagedType.I1)] bool executeMedianBlur,
            int imgMode,
            double dp,
            double minDist,
            double param1,
            double param2,
            int minRadius,
            int maxRadius,
            double grayGain,
            int grayMode);

        [DllImport("UVCCameraPlugin")]
        private static extern double getCircleCenter_x();

        [DllImport("UVCCameraPlugin")]
        private static extern double getCircleCenter_y();

        [DllImport("UVCCameraPlugin")]
        private static extern double getCircleRadius();

        private IntPtr _camera;
        private Texture2D _texture;
        private ImageProcessing _imageProcessing = new ImageProcessing();

        // Frame grabbing runs on its own thread. Grabbing one frame per Update() capped capture at
        // whatever the render loop managed (~20fps measured) even while the camera was streaming at
        // 120: Update() was draining a backlog of queued driver frames, so every frame it processed
        // was also stale. This thread drains the camera at full rate and Update() only uploads the
        // most recently finished frame.
        private Thread _captureThread;
        private volatile bool _captureRunning;
        private readonly object _frameLock = new object();
        private readonly object _paramLock = new object();

        // Serializes native VideoCapture access: the capture thread grabs while the Inspector's
        // Get/SetProperties buttons can call cap->set() from the main thread. Uncontended in the
        // steady state, so it costs the capture loop nothing.
        private readonly object _cameraLock = new object();

        // Double buffer. The capture thread always writes into _capturePixels, then swaps it with
        // _latestPixels under _frameLock. Both stay pinned for their whole lifetime so the native
        // side can memcpy straight into them.
        private Color32[] _capturePixels;
        private GCHandle _captureHandle;
        private IntPtr _capturePtr;
        private Color32[] _latestPixels;
        private GCHandle _latestHandle;
        private IntPtr _latestPtr;
        private Color32[] _displayPixels;   // main thread only; copied out from under _frameLock
        private bool _hasNewFrame;

        // Ball data is read off the native globals on the capture thread, immediately after the
        // call that produced them, so a frame detected at 120Hz cannot be overwritten by the next
        // frame before Update() gets to it.
        private BallRadiusAndPosition _latestBallData;
        private bool _hasBallData;

        // Frame centre, cached at startup so the capture thread never reads _cameraProperties
        // (which the Inspector buttons can rewrite from the main thread).
        private float _frameCenterX;
        private float _frameCenterY;

        // Snapshot of the tunables the capture thread needs, republished from the main thread so
        // Inspector/keyboard edits can never be read half-applied by the native call.
        private HT21Parameters _captureHt21Parameters;
        private int _captureImgMode;

        // Measures the actual rate frames are pulled off the camera (cap >> img in the plugin),
        // as opposed to CAP_PROP_FPS readback (which just echoes the requested mode on many UVC
        // drivers) or Unity's Time.deltaTime-based FPSDisplayer (which measures the render loop,
        // not the camera).
        private readonly System.Diagnostics.Stopwatch _captureFpsStopwatch = System.Diagnostics.Stopwatch.StartNew();
        private int _captureFrameCount;

        // Capture-thread frame rate, refreshed once a second. Shown here rather than logged:
        // this used to Debug.Log a full sentence every second, which floods the console during a
        // run and costs a stack-trace capture each time. Tick the box if you need it in the log.
        [SerializeField] private bool _logCaptureFps = false;
        [SerializeField] private float _measuredCaptureFps;

        [SerializeField] private Constants.ImgMode _imgMode;
        [SerializeField] private HT21Parameters _ht21Parameters;
        [SerializeField] private CameraProperties _cameraProperties;      // This is the struct you edit in the Inspector

        public Constants.ImgMode ImgMode
        {
            get => _imgMode;
            set => _imgMode = value;
        }

        // The HoughCircles result from imgMode 6. Computed for the on-screen overlay only - it no
        // longer feeds the machine, since imgMode 6 is a debug view.
        public BallRadiusAndPosition LatestHoughBallData { get; private set; }

        private BallRadiusAndPosition _lastAcceptedBall;
        private int _framesSinceBallAccepted = int.MaxValue;

        // How far the ball may appear to jump between frames and still be believed, in pixels.
        // At ~100fps and the balancing height 1mm is about 8px, so 150px is roughly 18mm in 10ms -
        // far more than any real ball motion, but still nothing like the width of the frame.
        private const float BallTrackingGatePixels = 150f;

        // Frames without an accepted ball after which the gate is dropped, so a ball that was
        // genuinely lost and put back somewhere else can be picked up again.
        private const int BallTrackingGateFrames = 30;

        // While there is no active lock, a candidate must sit within this many pixels of the
        // PREVIOUS frame's pending candidate to count as the "same" object continuing to be seen.
        private const float PendingLockTolerancePixels = 30f;

        // How many consecutive frames a candidate has to hold that position before it is trusted.
        // At ~100fps this costs about 30ms of extra latency the first time the ball is picked up.
        private const int PendingLockFramesRequired = 4;

        // Candidate being watched while there is no confirmed lock, and how many frames running it
        // has held near the same spot.
        private BallRadiusAndPosition _pendingLock;
        private int _pendingLockStreak;

        /// <summary>
        /// Chooses which detected blob is actually the ball.
        ///
        /// BallDataFromPixelBoarders returns candidates sorted by size, and the original code simply
        /// took the biggest - wrong whenever anything in the background is bigger, which on this rig
        /// is often true: the r-b metric that finds the (warm, orange) ball also fires on warm
        /// lighting and background surfaces outside the plate that are visible at this camera's wide
        /// 60 degree FOV.
        ///
        /// A size + proximity filter alone is not enough by itself, and an earlier version of this
        /// method proved it: whatever got accepted on the very FIRST frame - before there was any
        /// history to check proximity against - became "the ball" from then on, because the gate
        /// only checks distance to the PREVIOUS accepted position. If that first frame's biggest
        /// plausible blob was the ceiling, every later frame near it re-confirmed the ceiling, since
        /// the ceiling does not move and therefore always looks like "the same object, nearby".
        /// A lock earned that way, by size, self-sustains and never lets the real ball back in.
        ///
        /// So a lock now has to be EARNED, not just have the right radius:
        ///   - No lock:      a candidate must hold roughly the same spot for several consecutive
        ///                   frames (PendingLockFramesRequired) before it is trusted at all. A
        ///                   resting or slowly-moving ball trivially does this; background clutter
        ///                   flickers between frames as the detector's exact edges shift and rarely
        ///                   does. Until a candidate earns it, "no ball" is reported - safe, because
        ///                   the caller already treats that as "wait", not as a position to act on.
        ///   - Locked:       nearest plausible candidate to the last accepted position wins, as
        ///                   before - this is what lets it track a genuinely moving ball smoothly.
        /// </summary>
        private bool SelectBall(List<BallRadiusAndPosition> candidates, out BallRadiusAndPosition ball)
        {
            ball = default(BallRadiusAndPosition);

            if (candidates == null || candidates.Count == 0)
            {
                _framesSinceBallAccepted++;
                _pendingLockStreak = 0;
                return false;
            }

            List<BallRadiusAndPosition> plausible = null;

            foreach (var candidate in candidates)
            {
                if (candidate.Radius < _ht21Parameters.MinRadius ||
                    candidate.Radius > _ht21Parameters.MaxRadius)
                {
                    continue;
                }

                if (plausible == null)
                {
                    plausible = new List<BallRadiusAndPosition>(2);
                }

                plausible.Add(candidate);
            }

            if (plausible == null)
            {
                _framesSinceBallAccepted++;
                _pendingLockStreak = 0;
                return false;
            }

            if (_framesSinceBallAccepted <= BallTrackingGateFrames)
            {
                // LOCKED: nearest plausible candidate to where the ball just was.
                var nearest = -1f;
                var found = false;

                foreach (var candidate in plausible)
                {
                    var jump = new Vector2(
                        candidate.PositionX - _lastAcceptedBall.PositionX,
                        candidate.PositionY - _lastAcceptedBall.PositionY).magnitude;

                    if (jump > BallTrackingGatePixels)
                    {
                        continue;
                    }

                    if (!found || jump < nearest)
                    {
                        nearest = jump;
                        ball = candidate;
                        found = true;
                    }
                }

                if (!found)
                {
                    _framesSinceBallAccepted++;
                    return false;
                }

                _lastAcceptedBall = ball;
                _framesSinceBallAccepted = 0;
                return true;
            }

            // NOT LOCKED: a candidate has to hold its position for several frames before it earns
            // trust. Pick whichever plausible candidate is closest to last frame's pending spot -
            // or, if none is close, restart the streak on the plausible candidate nearest the
            // centre of the frame, since the ball is far more likely to be near the middle of the
            // plate than the background clutter at the edges is.
            BallRadiusAndPosition closest = default(BallRadiusAndPosition);
            var closestDistance = float.MaxValue;
            var haveClosest = false;

            foreach (var candidate in plausible)
            {
                var distance = _pendingLockStreak > 0
                    ? new Vector2(
                        candidate.PositionX - _pendingLock.PositionX,
                        candidate.PositionY - _pendingLock.PositionY).magnitude
                    : new Vector2(candidate.PositionX, candidate.PositionY).magnitude;

                if (!haveClosest || distance < closestDistance)
                {
                    closestDistance = distance;
                    closest = candidate;
                    haveClosest = true;
                }
            }

            var continuesPending = _pendingLockStreak > 0 && closestDistance <= PendingLockTolerancePixels;

            _pendingLock = closest;
            _pendingLockStreak = continuesPending ? _pendingLockStreak + 1 : 1;

            if (_pendingLockStreak < PendingLockFramesRequired)
            {
                return false;
            }

            ball = closest;
            _lastAcceptedBall = ball;
            _framesSinceBallAccepted = 0;
            _pendingLockStreak = 0;
            return true;
        }

        // Capture-thread frame rate, refreshed once a second. Read it off the inspector while
        // playing, or from here - it is no longer written to the console by default.
        public float MeasuredCaptureFps => _measuredCaptureFps;

        private void Awake()
        {
            _imgMode = Constants.ImgMode.Src;

            _cameraProperties = new CameraProperties()           // Set recommended starting properties for high-speed juggling
            {
                Width = c.CameraResolutionWidth,      // 640
                Height = c.CameraResolutionHeight,    // 480
                FPS = 120,                            // Measured: this camera really does stream 120fps over MSMF at its native 480x640 (see note in Start())
                AutoExposure = 0,                     // Manual, so the driver stops re-adjusting frame to frame
                Exposure = -5,                        // As per the known-good OpenCV 4.2 setup
                Gain = 110,                           // NOT the 4.2 screenshot's 15: that was on MSMF's scale, and these are
                                                      // now written through DSHOW, whose scale differs. 110 reproduces a
                                                      // comparable image (measured stream brightness ~114).
                Contrast = 25,                        // 4.2 value
                Saturation = 160,                     // 4.2 value
                Brightness = 64,                      // driver clamps at 64
                Gamma = 150,
                ISO = 100                             // Ignored by this driver (readback never moves off 1)
            };

            // Note: We no longer overwrite _cameraProperties here
            // This allows your Inspector values (640x480) to stay saved

            _ht21Parameters = new HT21Parameters()
            {
                ExecuteHT21 = false,
                ExecuteMedianBlue = true,  // Smooths noise, which matters more now that small/distant detections (~30px) are in play
                Dp = 1,
                MinDist = 120,
                // Retuned 2026-08-21 against the live ball, 200 consecutive frames per setting,
                // and checked visually against the ball's true edge.
                // Param1 is the important one: the ball throws a soft red halo/reflection onto the
                // ceiling, and a LOW Canny threshold locks onto that halo instead of the ball -
                // Param1=60 reported radius 148-159 where the ball was really ~93, which would
                // corrupt every radius->height conversion downstream. Raising it rejects the halo.
                // Measured: p1=150 -> 97.5fps, 200/200 detections, ONE candidate, r=93.7+-0.6,
                // x+-0.7 y+-0.9 (sub-pixel). p1=60 -> 12fps and radius overshoot.
                // Retuned for the HUE-GATED gray (the r-b tuning does not carry over - different
                // intensity distribution). Every setting from Param1 60..300 converges on the same
                // circle, so accuracy is unaffected; higher Param1 just cuts clutter and cost.
                // Measured on a live hue-gated frame: 150/32 -> 4 candidates at 18ms;
                // 200/32 -> 2 candidates at 6.5ms, same circle. NOTE the native overlay draws
                // EVERY candidate, which is why extra circles appear on screen - the value the
                // code actually uses is circles[0], the first one.
                Param1 = 200,
                Param2 = 32,
                GrayGain = 1,      // OFF. Only raise if the image is genuinely under-exposed - see the note on the field
                GrayMode = 0,      // r-b. Verified best on the CORRECTLY LIT scene: 1 object, centre (300,210),
                                   // r=168.7, circularity 0.78 - beating hue-gating (0.75) and saturation x
                                   // darkness (3 objects). The fancier metrics were only ever compensating for
                                   // a badly lit ball; with the lighting fixed the original metric wins.
                                   // If the lighting degrades again, try 1 then 2 - see the note on the field.
                MinRadius = 28,    // NOT the 4.2 screenshot's 100: that would reject the ball near the 200mm apex, where it
                                   // is only ~34px. Measured identical accuracy and rate at 28, so 28 keeps the full flight range.
                MaxRadius = 260    // Raised from 200 when the working origin moved to 20mm above the
                                   // mechanical dead position: the ball now RESTS at ~223px (camera only
                                   // ~52mm away), which the old 200 cap rejected outright. 260 gives real
                                   // margin over that, same margin-over-worst-case spirit as the original
                                   // 200 had over its own 168px rest point.
                                   // Affects more than the imgMode 6 debug view now: UVCCameraPlugin's own
                                   // SelectBall() also uses this as a plausibility filter on EVERY imgMode's
                                   // candidates (added when it also started rejecting the ceiling as "the
                                   // ball") - so this is now a real gate on what imgMode 7 hands the
                                   // machine, not just cosmetic. Re-check this number if the origin offset
                                   // changes again - see FOVCalculations.CameraToPlateDistanceAtOrigin.
            };
        }

        void Start()
        {
            // Controls must be written BEFORE the MSMF stream is opened - the DirectShow pass
            // needs exclusive access to the device.
            ApplyCameraControls();

            _camera = getCamera();

            // NOTE ON BACKEND / FORMAT / RESOLUTION - measured directly against this camera by
            // driving the plugin DLL outside Unity, not assumed:
            //  * The 20fps ceiling was the OLD opencv_world420.dll (OpenCV 4.2). Its MSMF layer
            //    enables MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING, which hides the camera's
            //    compressed modes, pinning it to NV12 at exactly 20fps. No property, set() order,
            //    resolution or backend worked around it: CAP_PROP_FOURCC=MJPG was rejected
            //    outright by MSMF (set() returned 0), and CAP_DSHOW would not leave YUY2/30fps.
            //    Exposure and auto-exposure had no effect on the rate at all.
            //  * The plugin is now built against OpenCV 4.13, where MSMF reaches a real 120fps on
            //    this camera. getCamera() pins CAP_MSMF for that reason.
            //  * MJPEG still does not need requesting: CAP_PROP_FOURCC remains a no-op on MSMF,
            //    and 120fps is reached without it.
            //  * The camera's native mode is PORTRAIT 480x640, not 640x480 - unchanged between
            //    OpenCV 4.2 and 4.13, so the existing FOV calibration still holds. Requesting
            //    640x480 (or 1280x720) silently resolves to 480x640, and requesting 800x600
            //    breaks capture outright (every grab fails with E_OUTOFMEMORY). The
            //    GetCameraProperties() readback below is what the Texture2D is sized from, so the
            //    swapped-looking 480x640 in the Inspector is correct - do not "fix" it to 640x480.

            ConfigureStreamFormat();

            // No sensor-control writes here on purpose: every setCameraProperty() for exposure,
            // gain, saturation, contrast, brightness, gamma, auto-exposure, autofocus and auto-WB
            // is a silent no-op on the MSMF capture (measured - set() does nothing and the
            // readback never moves off the driver defaults, in any call order). They are applied
            // by ApplyCameraControls() above, before this capture was opened.

            GetCameraProperties(); // Refresh the UI with actual hardware values

            // Hand the managed pixel-scanning code the resolution the driver really delivers.
            // Constants.CameraResolutionWidth/Height are only what we REQUESTED (640x480); this
            // camera resolves that to its native portrait 480x640, and indexing the buffer with
            // the requested 640 stride is what broke imgMode 7's ball detection.
            c.FrameWidth = (int)_cameraProperties.Width;
            c.FrameHeight = (int)_cameraProperties.Height;

            // FIX: Texture format changed to RGB24 to prevent slanted/ghosting artifacts
            _texture = new Texture2D((int)_cameraProperties.Width, (int)_cameraProperties.Height,
                TextureFormat.RGB24, false);

            _frameCenterX = (float)_cameraProperties.Width / 2f;
            _frameCenterY = (float)_cameraProperties.Height / 2f;

            var pixelCount = _texture.width * _texture.height;
            _capturePixels = new Color32[pixelCount];
            _latestPixels = new Color32[pixelCount];
            _displayPixels = new Color32[pixelCount];

            _captureHandle = GCHandle.Alloc(_capturePixels, GCHandleType.Pinned);
            _capturePtr = _captureHandle.AddrOfPinnedObject();
            _latestHandle = GCHandle.Alloc(_latestPixels, GCHandleType.Pinned);
            _latestPtr = _latestHandle.AddrOfPinnedObject();

            foreach (var comp in _volume.profile.components)
            {
                if (comp is OverlayComponent oc)
                {
                    oc.overlayParameter.value = _texture;
                }
            }

            StartCaptureThread();
        }

        // Resolution and frame rate, i.e. the properties MSMF *does* honour. Split out of Start()
        // so the SetProperties restart can re-apply it after reopening the capture.
        private void ConfigureStreamFormat()
        {
            _cameraProperties.Width = c.CameraResolutionWidth;   // requested 640, resolves to 480
            _cameraProperties.Height = c.CameraResolutionHeight; // requested 480, resolves to 640

            setCameraProperty(_camera, (int)vcp.CAP_PROP_FRAME_WIDTH, _cameraProperties.Width);
            setCameraProperty(_camera, (int)vcp.CAP_PROP_FRAME_HEIGHT, _cameraProperties.Height);

            var requestedFps = _cameraProperties.FPS;
            var fpsSetResult = setCameraProperty(_camera, (int)vcp.CAP_PROP_FPS, requestedFps);

            var readbackFps = getCameraProperty(_camera, (int)vcp.CAP_PROP_FPS);
            var readbackFourCcInt = (int)getCameraProperty(_camera, (int)vcp.CAP_PROP_FOURCC);
            var readbackFourCc = new string(new[]
            {
                (char)(readbackFourCcInt & 0xFF),
                (char)((readbackFourCcInt >> 8) & 0xFF),
                (char)((readbackFourCcInt >> 16) & 0xFF),
                (char)((readbackFourCcInt >> 24) & 0xFF)
            });
            var backendId = getCameraProperty(_camera, (int)vcp.CAP_PROP_BACKEND);
            Debug.Log($"[Camera] Requested FPS={requestedFps}, cap->set() returned={fpsSetResult} (0=driver rejected the call), " +
                      $"driver readback FPS={readbackFps}, FOURCC readback='{readbackFourCc}', " +
                      $"backend ID={backendId} (700=DSHOW, 1400=MSMF, 0=auto/unset) " +
                      "(use the [Camera] Measured capture FPS log to see the real achieved rate).");
        }

        private void StartCaptureThread()
        {
            PublishCaptureParameters();

            _captureRunning = true;
            _captureThread = new Thread(CaptureLoop)
            {
                Name = "UVCCameraCapture",
                IsBackground = true,
                Priority = System.Threading.ThreadPriority.AboveNormal
            };
            _captureThread.Start();
        }

        // Returns false if the thread refused to stop, in which case nothing it touches - the
        // camera handle or the pinned buffers - may be torn down.
        private bool StopCaptureThread()
        {
            _captureRunning = false;

            if (_captureThread == null)
            {
                return true;
            }

            var stopped = _captureThread.Join(1000);
            _captureThread = null;

            if (!stopped)
            {
                Debug.LogWarning("[Camera] Capture thread did not stop within 1s; leaving the camera " +
                                 "open and the buffers pinned rather than freeing memory the native " +
                                 "side may still be writing into.");
            }

            return stopped;
        }

        // Copies the live tunables into the snapshot the capture thread reads.
        private void PublishCaptureParameters()
        {
            lock (_paramLock)
            {
                _captureHt21Parameters = _ht21Parameters;
                _captureImgMode = (int)_imgMode == 7 ? 5 : (int)_imgMode;
            }
        }

        // Runs off the main thread for the whole session: grab -> process -> publish, as fast as
        // the camera and the native pipeline allow, independently of Unity's frame rate.
        private void CaptureLoop()
        {
            while (_captureRunning)
            {
                HT21Parameters parameters;
                int imgMode;
                lock (_paramLock)
                {
                    parameters = _captureHt21Parameters;
                    imgMode = _captureImgMode;
                }

                bool grabbed;
                var ballData = default(BallRadiusAndPosition);
                lock (_cameraLock)
                {
                    if (!_captureRunning)
                    {
                        return;
                    }

                    grabbed = getCameraTexture(
                        _camera,
                        _capturePtr,
                        parameters.ExecuteHT21,
                        parameters.ExecuteMedianBlue,
                        imgMode,
                        parameters.Dp,
                        parameters.MinDist,
                        parameters.Param1,
                        parameters.Param2,
                        parameters.MinRadius,
                        parameters.MaxRadius,
                        parameters.GrayGain,
                        parameters.GrayMode);

                    if (grabbed)
                    {
                        // Read the circle globals here, while they still belong to the frame that
                        // was just processed.
                        ballData = new BallRadiusAndPosition()
                        {
                            Radius = (float)getCircleRadius(),
                            PositionX = -(float)getCircleCenter_x() + _frameCenterX,
                            PositionY = -(float)getCircleCenter_y() + _frameCenterY
                        };
                    }
                }

                if (!grabbed)
                {
                    // Dropped grab: the native side left both the pixel buffer and the circle
                    // globals untouched, so publish nothing and back off instead of spinning a
                    // core re-trying a camera that is not delivering.
                    Thread.Sleep(1);
                    continue;
                }

                lock (_frameLock)
                {
                    var swappedPixels = _latestPixels;
                    var swappedPtr = _latestPtr;
                    var swappedHandle = _latestHandle;

                    _latestPixels = _capturePixels;
                    _latestPtr = _capturePtr;
                    _latestHandle = _captureHandle;

                    _capturePixels = swappedPixels;
                    _capturePtr = swappedPtr;
                    _captureHandle = swappedHandle;

                    _hasNewFrame = true;
                    _latestBallData = ballData;
                    _hasBallData = parameters.ExecuteHT21;
                    _captureFrameCount++;
                }
            }
        }

        private double GetCameraProperty(vcp property)
        {
            lock (_cameraLock)
            {
                return getCameraProperty(_camera, (int) property);
            }
        }

        private void SetCameraProperty(vcp property, double value)
        {
            lock (_cameraLock)
            {
                setCameraProperty(_camera, (int) property, value);
            }
        }

        // Called from Start() and from the Inspector's GetProperties button, i.e. from the main
        // thread while the capture thread may be mid-grab - hence _cameraLock.
        public void GetCameraProperties()
        {
            lock (_cameraLock)
            {
                _cameraProperties.Width = getCameraProperty(_camera, (int)vcp.CAP_PROP_FRAME_WIDTH);
                _cameraProperties.Height = getCameraProperty(_camera, (int)vcp.CAP_PROP_FRAME_HEIGHT);
                _cameraProperties.FPS = getCameraProperty(_camera, (int)vcp.CAP_PROP_FPS);

                // Deliberately NOT reading back exposure / gain / contrast / saturation / ISO.
                //
                // MSMF reports its own unrelated numbers for those - measured on this rig it
                // answers exposure -6, contrast 0, saturation 70 no matter what was actually
                // applied. Storing them here overwrote the calibrated values (exposure -5, gain
                // 110, saturation 160, contrast 25) on the very first frame, and then any later
                // SetCameraProperties() pushed THOSE back out through the DSHOW pass - quietly
                // replacing a tuned image with a dark, washed-out one that the ball detector
                // cannot work with. Width/Height/FPS are real and are still read.
            }
        }

        // Writes the sensor controls through the plugin's DirectShow pass. OpenCV's MSMF backend
        // - the only one that reaches 120fps on this camera - ignores every camera control, so the
        // values are pushed through a throwaway DSHOW capture instead and persist in the driver
        // into the MSMF stream. Requires that nothing is currently streaming.
        private void ApplyCameraControls()
        {
            var readback = new double[7];
            var applied = applyCameraControls(
                _cameraProperties.AutoExposure,
                _cameraProperties.Exposure,
                _cameraProperties.Gain,
                _cameraProperties.Saturation,
                _cameraProperties.Contrast,
                _cameraProperties.Brightness,
                _cameraProperties.Gamma,
                readback);

            if (!applied)
            {
                Debug.LogWarning("[Camera] Could not open the camera on DirectShow to write the sensor " +
                                 "controls - something else is holding the device. Exposure/gain/etc will " +
                                 "stay at whatever the driver was last left with.");
                return;
            }

            Debug.Log($"[Camera] Controls applied via DSHOW - driver accepted: AutoExposure={readback[0]}, " +
                      $"Exposure={readback[1]}, Gain={readback[2]}, Saturation={readback[3]}, " +
                      $"Contrast={readback[4]}, Brightness={readback[5]}, Gamma={readback[6]}. " +
                      "NOTE: the streaming MSMF capture reports its own unrelated values for these, so " +
                      "judge by the image, not by the Camera Properties readback below.");
        }

        // The Inspector's SetProperties button. Controls can only be written while nothing is
        // streaming, so the MSMF capture is torn down, the controls are pushed through DSHOW, and
        // the stream is rebuilt. The pinned buffers are reused, so the resolution must not change.
        public void SetCameraProperties()
        {
            if (_camera == IntPtr.Zero)
            {
                Debug.LogWarning("[Camera] Camera is not open - enter Play mode before applying properties.");
                return;
            }

            if (!StopCaptureThread())
            {
                return;
            }

            releaseCamera(_camera);
            _camera = IntPtr.Zero;

            ApplyCameraControls();

            _camera = getCamera();
            ConfigureStreamFormat();
            GetCameraProperties();

            var pixelCount = (int)_cameraProperties.Width * (int)_cameraProperties.Height;
            if (pixelCount != _displayPixels.Length)
            {
                Debug.LogError($"[Camera] Resolution came back as {_cameraProperties.Width}x{_cameraProperties.Height} " +
                               "after the restart, which no longer matches the pinned buffers. Leave Play mode " +
                               "and re-enter it.");
                return;
            }

            StartCaptureThread();
        }

        public BallRadiusAndPosition UpdateImageProcessing()
        {
            // Input handling for image modes
            if (Input.GetKeyDown(KeyCode.B)) 
            {
                DecrementImgMode();
            }

            if (Input.GetKeyDown(KeyCode.N)) 
            {
                _captionView.SetText(Constants.Captions[(int)_imgMode]);
            }

            if (Input.GetKeyDown(KeyCode.M)) 
            {
                IncrementImgMode();
            }

             foreach (var c in _volume.profile.components)
            {
                if (c is OverlayComponent oc)
                {
                    if (_imgMode == Constants.ImgMode.Red)
                    {
                        oc.tintColor.value = Color.red;
                    }
                    else if (_imgMode == Constants.ImgMode.Green)
                    {
                        oc.tintColor.value = Color.green;
                    }
                    else if (_imgMode == Constants.ImgMode.Blue)
                    {
                        oc.tintColor.value = Color.blue;
                    }
                    else
                    {
                        oc.tintColor.value = Color.white;
                    }
                }
            }

            _ht21Parameters.ExecuteHT21 = _imgMode == Constants.ImgMode.CustomgrayWithCirclesOverlayed;
            PublishCaptureParameters();

            BallRadiusAndPosition ballData;
            bool hasNewFrame;
            bool hasBallData;
            bool fpsReportDue = false;
            int framesSinceLastReport = 0;

            lock (_frameLock)
            {
                hasNewFrame = _hasNewFrame;
                if (hasNewFrame)
                {
                    // Copy out instead of handing _latestPixels straight to SetPixels32: the
                    // capture thread reclaims that array as its write target on the next swap.
                    Array.Copy(_latestPixels, _displayPixels, _displayPixels.Length);
                    _hasNewFrame = false;
                }

                ballData = _latestBallData;
                hasBallData = _hasBallData;

                if (_captureFpsStopwatch.Elapsed.TotalSeconds >= 1.0)
                {
                    fpsReportDue = true;
                    framesSinceLastReport = _captureFrameCount;
                    _captureFrameCount = 0;
                }
            }

            if (fpsReportDue)
            {
                var elapsed = _captureFpsStopwatch.Elapsed.TotalSeconds;
                _captureFpsStopwatch.Restart();

                _measuredCaptureFps = (float)(framesSinceLastReport / elapsed);

                if (_logCaptureFps)
                {
                    Debug.Log($"[Camera] Measured capture FPS={_measuredCaptureFps:0.0} " +
                              $"({framesSinceLastReport} frames grabbed in {elapsed:0.00}s) - this is " +
                              "the capture thread's rate, no longer tied to the render loop.");
                }
            }

            // ONLY imgMode 7 (CustomgrayWithInternalImageProcessing) drives the machine.
            // imgMode 6 (CustomgrayWithCirclesOverlayed) still runs HoughCircles and paints its
            // circles so the detection can be inspected, but it reports this neutral placeholder
            // instead, so the machine does not react to it.
            var result = new BallRadiusAndPosition()
            {
                Radius = 0.1f,
                PositionX = 0f + _frameCenterX,
                PositionY = 0f + _frameCenterY
            };

            if ((int) _imgMode == 7)
            {
                // Managed detection, so this runs at the Update() rate rather than the capture
                // thread's rate. It also paints its findings into the pixel buffer, so it has to
                // run BEFORE the texture upload or that overlay never reaches the screen.
                var ballPosAndRadius = _imageProcessing.BallDataFromPixelBoarders(_displayPixels);

                if (SelectBall(ballPosAndRadius, out var ball))
                {
                    result = ball;
                }
            }

            // Kept for inspection/logging; deliberately not returned - see above.
            LatestHoughBallData = hasBallData ? ballData : default(BallRadiusAndPosition);

            if (hasNewFrame)
            {
                _texture.SetPixels32(_displayPixels);
                _texture.Apply();
            }

            return result;
        }

        public void IncrementImgMode()
        {
            _imgMode++;
            if ((int)_imgMode >= Enum.GetNames(typeof(Constants.ImgMode)).Length) 
            {
                _imgMode = 0;
            }

            _captionView.SetText(Constants.Captions[(int)_imgMode]);
        }

        public void DecrementImgMode()
        {
            _imgMode--;
            if ((int)_imgMode < 0) 
            {
                _imgMode = (Constants.ImgMode)Enum.GetNames(typeof(Constants.ImgMode)).Length - 1;
            }
            
            _captionView.SetText(Constants.Captions[(int)_imgMode]);
        }

        private void OnApplicationQuit()
        {
            StopCapture();
        }

        private void OnDestroy()
        {
            StopCapture();
        }

        // The capture thread must be joined before the camera is released and the buffers
        // unpinned: it is otherwise sitting inside getCameraTexture() using both of them.
        private void StopCapture()
        {
            if (!StopCaptureThread())
            {
                return;
            }

            if (_captureHandle.IsAllocated) _captureHandle.Free();
            if (_latestHandle.IsAllocated) _latestHandle.Free();

            if (_camera != IntPtr.Zero)
            {
                releaseCamera(_camera);
                _camera = IntPtr.Zero;
            }
        }
    }

    [Serializable]
    public struct CameraProperties
    {
        public double Width;
        public double Height;
        public double FPS;

        // Sensor controls. These are written through the plugin's DirectShow pass (see
        // ApplyCameraControls) - OpenCV's MSMF backend, which carries the 120fps stream, ignores
        // every one of them. Press SetProperties in the Inspector to re-apply after editing.
        public double AutoExposure;   // 0 = manual, 1 = auto
        public double Exposure;       // log2 seconds, e.g. -6 = 1/64s (clamped to the frame period)
        public double Gain;
        public double Contrast;
        public double Saturation;
        public double Brightness;
        public double Gamma;
        public double ISO;            // ignored by this driver, kept for the Inspector
    }

    [Serializable]
    public struct HT21Parameters
    {
        public bool ExecuteHT21;
        public bool ExecuteMedianBlue;

        // Multiplies the r-b image before the blur and HoughCircles. Leave at 1 whenever the
        // camera controls are doing their job: with the exposure correctly applied the ball
        // separates strongly (r-b p99 = 151), and raising this SATURATES the image, floods Hough
        // with edge points and destroys both speed and accuracy - measured 0.6fps with the centre
        // jittering +-36/+-65px at GrayGain=3. It exists only to rescue a genuinely under-exposed
        // scene, where raw separation can fall to ~9 grey levels and nothing is detected at all.
        public double GrayGain;

        // How the "custom gray" that both detectors run on is built. Switchable at runtime so a
        // failing scene can be diagnosed without a native rebuild. Measured on a real ball frame
        // (ball covered / background false-positives / blob circularity):
        //   0 = r - b .................... 49% / 13%  / 0.05  - collapses wherever the ball is
        //                                  shadowed, because a shadowed orange ball reads brown.
        //   1 = orange-hue x saturation .. 80% / 5.8% / 0.76  - but a warm TAN/WOODEN background
        //                                  sits in the same hue band as an orange ball and lights
        //                                  up instead of it.
        //   2 = saturation x darkness .... 98% / 9.4% / 0.83  - best. The ball is both more
        //                                  saturated (80.8 vs 32.2) AND darker (value 100.6 vs
        //                                  144.7) than the background, and unlike hue that holds
        //                                  even when the background is warm-coloured.
        // NOTE: changing this changes the measured radius, so the FOV calibration must be redone.
        public int GrayMode;

        public double Dp;
        public double MinDist;
        public double Param1;
        public double Param2;
        public int minRadius; // Fixed casing to match struct standards
        public int maxRadius;
        public int MinRadius { get => minRadius; set => minRadius = value; }
        public int MaxRadius { get => maxRadius; set => maxRadius = value; }
    }

    public struct BallRadiusAndPosition
    {
        public float Radius;
        public float PositionX;
        public float PositionY;
    }
}