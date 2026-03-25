using System;
using System.Linq;
using System.Runtime.InteropServices;
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
        private static extern void getCameraTexture(
            IntPtr camera,
            IntPtr data,
            bool executeHT21,
            bool executeMedianBlur,
            int imgMode,
            double dp,
            double minDist,
            double param1,
            double param2,
            int minRadius,
            int maxRadius);

        [DllImport("UVCCameraPlugin")]
        private static extern double getCircleCenter_x();

        [DllImport("UVCCameraPlugin")]
        private static extern double getCircleCenter_y();

        [DllImport("UVCCameraPlugin")]
        private static extern double getCircleRadius();

        private IntPtr _camera;
        private Texture2D _texture;
        private Color32[] _pixels;
        private GCHandle _pixelsHandle;
        private IntPtr _pixelsPtr;
        private ImageProcessing _imageProcessing = new ImageProcessing();

        [SerializeField] private Constants.ImgMode _imgMode;
        [SerializeField] private HT21Parameters _ht21Parameters;

        // This is the struct you edit in the Inspector
        [SerializeField] private CameraProperties _cameraProperties;

        public Constants.ImgMode ImgMode
        {
            set => _imgMode = value;
        }

        private void Awake()
        {
            _imgMode = Constants.ImgMode.Src;

            // Set recommended starting properties for high-speed juggling
            _cameraProperties = new CameraProperties()
            {
                Width = c.CameraResolutionWidth,      // 640
                Height = c.CameraResolutionHeight,    // 480
                FPS = 60,                             // High frame rate for tracking
                Exposure = -2,                        // Low exposure to reduce motion blur
                Gain = 25,                            // Bring back brightness
                Contrast = 25,                        // Help the orange ball stand out
                Saturation = 138,                     // Standard color depth
                ISO = 100                             // Low, steady ISO to prevent flickering
            };

            // Note: We no longer overwrite _cameraProperties here
            // This allows your Inspector values (640x480) to stay saved

            _ht21Parameters = new HT21Parameters()
            {
                ExecuteHT21 = false,
                ExecuteMedianBlue = false,
                Dp = 1,
                MinDist = 120,
                Param1 = 60,
                Param2 = 30,
                MinRadius = 12,
                MaxRadius = 160
            };
        }

        void Start()
        {
            _camera = getCamera();

            // 1. FORCE the correct resolution from Constants to bypass flipped Inspector values

            _cameraProperties.Width = c.CameraResolutionWidth;  // Forces 640
            _cameraProperties.Height = c.CameraResolutionHeight; // Forces 480

            // FIX: Set Width and Height correctly
            setCameraProperty(_camera, (int)vcp.CAP_PROP_FRAME_WIDTH, _cameraProperties.Width);
            setCameraProperty(_camera, (int)vcp.CAP_PROP_FRAME_HEIGHT, _cameraProperties.Height);

            setCameraProperty(_camera, (int)vcp.CAP_PROP_EXPOSURE, _cameraProperties.Exposure);
            setCameraProperty(_camera, (int)vcp.CAP_PROP_GAIN, _cameraProperties.Gain);
            setCameraProperty(_camera, (int)vcp.CAP_PROP_SATURATION, _cameraProperties.Saturation);
            setCameraProperty(_camera, (int)vcp.CAP_PROP_CONTRAST, _cameraProperties.Contrast);

            GetCameraProperties();
            GetCameraProperties(); // Refresh the UI with actual hardware values

            // FIX: Texture format changed to RGB24 to prevent slanted/ghosting artifacts
            _texture = new Texture2D((int)_cameraProperties.Width, (int)_cameraProperties.Height,
                TextureFormat.RGB24, false);

            _pixels = _texture.GetPixels32();

            _pixelsHandle = GCHandle.Alloc(_pixels, GCHandleType.Pinned);
            _pixelsPtr = _pixelsHandle.AddrOfPinnedObject();

            foreach (var comp in _volume.profile.components)
            {
                if (comp is OverlayComponent oc)
                {
                    oc.overlayParameter.value = _texture;
                }
            }
        }

        public void GetCameraProperties()
        {
            _cameraProperties.Width = getCameraProperty(_camera, (int)vcp.CAP_PROP_FRAME_WIDTH);
            _cameraProperties.Height = getCameraProperty(_camera, (int)vcp.CAP_PROP_FRAME_HEIGHT);
            _cameraProperties.FPS = getCameraProperty(_camera, (int)vcp.CAP_PROP_FPS);
            _cameraProperties.Exposure = getCameraProperty(_camera, (int)vcp.CAP_PROP_EXPOSURE);
            _cameraProperties.Gain = getCameraProperty(_camera, (int)vcp.CAP_PROP_GAIN);
            _cameraProperties.Contrast = getCameraProperty(_camera, (int)vcp.CAP_PROP_CONTRAST);
            _cameraProperties.ISO = getCameraProperty(_camera, (int)vcp.CAP_PROP_ISO_SPEED);
            _cameraProperties.Saturation = getCameraProperty(_camera, (int)vcp.CAP_PROP_SATURATION);
        }

        public void SetCameraProperties()
        {
            setCameraProperty(_camera, (int)vcp.CAP_PROP_EXPOSURE, _cameraProperties.Exposure);
            setCameraProperty(_camera, (int)vcp.CAP_PROP_GAIN, _cameraProperties.Gain);
            setCameraProperty(_camera, (int)vcp.CAP_PROP_CONTRAST, _cameraProperties.Contrast);
            setCameraProperty(_camera, (int)vcp.CAP_PROP_ISO_SPEED, _cameraProperties.ISO);
            setCameraProperty(_camera, (int)vcp.CAP_PROP_SATURATION, _cameraProperties.Saturation);
        }

        public BallRadiusAndPosition UpdateImageProcessing()
        {
            // Input handling for image modes
            if (Input.GetKeyDown(KeyCode.B)) DecrementImgMode();
            if (Input.GetKeyDown(KeyCode.N)) _captionView.SetText(Constants.Captions[(int)_imgMode]);
            if (Input.GetKeyDown(KeyCode.M)) IncrementImgMode();

            _ht21Parameters.ExecuteHT21 = _imgMode == Constants.ImgMode.CustomgrayWithCirclesOverlayed;

            getCameraTexture(
                _camera,
                _pixelsPtr,
                _ht21Parameters.ExecuteHT21,
                _ht21Parameters.ExecuteMedianBlue,
                (int)_imgMode == 7 ? 5 : (int)_imgMode,
                _ht21Parameters.Dp,
                _ht21Parameters.MinDist,
                _ht21Parameters.Param1,
                _ht21Parameters.Param2,
                _ht21Parameters.MinRadius,
                _ht21Parameters.MaxRadius
            );

            _texture.SetPixels32(_pixels);
            _texture.Apply();

            if ((int)_imgMode == 7)
            {
                var ballPosAndRadius = _imageProcessing.BallDataFromPixelBoarders(_pixels);
                return ballPosAndRadius.FirstOrDefault();
            }

            if (_imgMode == Constants.ImgMode.CustomgrayWithCirclesOverlayed)
            {
                return new BallRadiusAndPosition()
                {
                    Radius = (float)getCircleRadius(),
                    PositionX = -(float)getCircleCenter_x() + (float)_cameraProperties.Width / 2f,
                    PositionY = -(float)getCircleCenter_y() + (float)_cameraProperties.Height / 2f
                };
            }

            return new BallRadiusAndPosition()
            {
                Radius = 0.1f,
                PositionX = 0f + (float)_cameraProperties.Width / 2f,
                PositionY = 0f + (float)_cameraProperties.Height / 2f
            };
        }

        public void IncrementImgMode()
        {
            _imgMode++;
            if ((int)_imgMode >= Enum.GetNames(typeof(Constants.ImgMode)).Length) _imgMode = 0;
            _captionView.SetText(Constants.Captions[(int)_imgMode]);
        }

        public void DecrementImgMode()
        {
            _imgMode--;
            if ((int)_imgMode < 0) _imgMode = (Constants.ImgMode)Enum.GetNames(typeof(Constants.ImgMode)).Length - 1;
            _captionView.SetText(Constants.Captions[(int)_imgMode]);
        }

        private void OnApplicationQuit()
        {
            if (_pixelsHandle.IsAllocated) _pixelsHandle.Free();
            releaseCamera(_camera);
        }
    }

    [Serializable]
    public struct CameraProperties
    {
        public double Width;
        public double Height;
        public double FPS;
        public double Exposure;
        public double Gain;
        public double Contrast;
        public double ISO;
        public double Saturation;
    }

    [Serializable]
    public struct HT21Parameters
    {
        public bool ExecuteHT21;
        public bool ExecuteMedianBlue;
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