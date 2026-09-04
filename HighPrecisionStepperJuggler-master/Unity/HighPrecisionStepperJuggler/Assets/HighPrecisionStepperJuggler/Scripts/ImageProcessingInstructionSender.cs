using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using HighPrecisionStepperJuggler.MachineLearning;
using UniRx;
using UnityEngine;
using c = HighPrecisionStepperJuggler.Constants;

namespace HighPrecisionStepperJuggler
{
    public class ImageProcessingInstructionSender : MonoBehaviour
    {
        [SerializeField] private UVCCameraPlugin _cameraPlugin;
        [SerializeField] private MachineController _machineController;
        [SerializeField] private BallPositionVisualizer _ballPositionVisualizer;
        [SerializeField] private BallDataDebugView _ballDataDebugView;
        [SerializeField] private PredictedPositionVisualizer _predictedPositionVisualizer;
        [SerializeField] private GradientDescentView _gradientDescentViewX;
        [SerializeField] private GradientDescentView _gradientDescentViewY;
        [SerializeField] private GradientDescentView _gradientDescentViewZ;
        [SerializeField] private CrossVisualizer _targetCrossVisualizer;
        [SerializeField] private CrossVisualizer _currentPositionCrossVisualizer;
        [SerializeField] private MachineStateView _machineStateView;

        private readonly GradientDescent _gradientDescentX = new GradientDescent(
            Constants.NumberOfTrainingSetsUsedForXYGD,
            Constants.NumberOfGDUpdateCyclesXY,
            Constants.AlphaXY
        );

        private readonly GradientDescent _gradientDescentY = new GradientDescent(
            Constants.NumberOfTrainingSetsUsedForXYGD,
            Constants.NumberOfGDUpdateCyclesXY,
            Constants.AlphaXY
        );

        private readonly GradientDescent _gradientDescentZ = new GradientDescent(
            Constants.NumberOfTrainingSetsUsedForHeightGD,
            Constants.NumberOfGDUpdateCyclesHeight,
            Constants.AlphaHeight
        );

        // Which set of control strategies to build in Start().
        public enum StrategyProgram
        {
            // Bring-up program: hold the ball on the plate and nothing else. Start here.
            BalancingOnly,

            // The original ~100-stage choreography from the paper. It starts STRIKING the ball
            // about 2.2s after Space (Bouncing -> BouncingStrong -> TwoStepBouncing -> ...), so
            // the ball leaving the plate is what it is asking for, not a malfunction.
            FullJugglingDemo,

            // A short, bounded bounce sequence: settle, then a handful of gentle 10mm bounces with
            // XY correction on every hit. Added AFTER the two above so it does not renumber either
            // of them, in case FullJugglingDemo was ever picked and its int got serialized into the
            // scene. Built entirely from BallControlStrategyFactory.Bouncing(), the one bounce stage
            // that was checked and is safe on this rig - a 50->60mm hop peaks around 4.5mm of apex
            // and a few mm of lateral throw, nothing like BouncingStrong's 50->80mm slam. Runs
            // SmallJugglingBounceCount times and then lands, rather than running forever, so it
            // reads as a demo rather than a mode.
            SmallJugglingDemo
        }

        [SerializeField] private StrategyProgram _strategyProgram = StrategyProgram.BalancingOnly;

        [Header("Small juggling demo")]
        // The choreography: rise to _smallJugglingBaseHeightMm above the working origin, settle the
        // ball there, bounce it in a steady rhythm for _smallJugglingBounceSeconds while correcting
        // tilt on every stroke, then STOP oscillating and just balance until the ball is genuinely
        // settled on the centre, and only then step gradually down to the origin. Heights are in mm
        // ABOVE THE WORKING ORIGIN, not above the mechanical dead position - the working origin is
        // itself Constants.OriginHeightOffset above that.
        // 40mm above the working origin, which with a 10mm origin puts the plate 50mm above the
        // mechanical dead position while juggling. This is where the ball spends the whole bouncing
        // phase, so it is what decides how much room it has to move before leaving the camera's
        // view: +-49.2mm in X here, against +-32.5mm down at the origin.
        [SerializeField] private float _smallJugglingBaseHeightMm = 40f;
        [SerializeField] private float _smallJugglingOscillationMm = 25f;

        // The bounce is four phases, not two - see BallControlStrategyFactory.RhythmicBouncing.
        // Retuned 2026-08-28 after the previous single-move-time 30mm/0.10s setting shook the whole
        // structure hard enough to throw the ball off the plate. The ball was not being lost to the
        // hop itself (6.3mm) but to the frame vibration the motion excited.
        //
        // RISE - the only phase that has to be hard. Peak plate acceleration is
        // pi^2 * rise / (2 * riseTime^2) and the ball only separates when that exceeds 1g; below it
        // the plate carries the ball up in contact and nothing juggles. 25mm/0.10s = 1.26g, down
        // from 1.51g, which drops the ball's launch speed 0.353 -> 0.238 m/s and the hop 6.3 -> 2.9mm.
        // Peak step rate ~11500/s, well under this firmware's ~25000/s ISR ceiling. Do NOT set any
        // of these times to 0.05 or below: the firmware clamps anything under MOVE_DURATION (0.05s,
        // Constants.h) up to that floor, so asking for less silently gets you 0.05s.
        [SerializeField] private float _smallJugglingRiseTime = 0.1f;

        // TOP DWELL - sent as a move to the height the plate is already at, so it genuinely holds
        // still. Sized to cover the ball's flight: at 1.26g it separates 0.079s into the rise and
        // lands back about 0.03s after the rise ends, so 0.08s catches it on a stationary plate.
        [SerializeField] private float _smallJugglingTopDwellTime = 0.08f;

        // FALL - deliberately much slower than the rise. The old setting ran the fall at the rise's
        // speed, making every cycle contain TWO 1.51g events when only the rise needs to beat 1g;
        // the fall launches nothing, so its speed was pure structural excitation for no benefit.
        // 25mm/0.22s = 0.26g, about six times gentler, and it keeps the ball in contact on the way
        // down instead of flinging it.
        [SerializeField] private float _smallJugglingFallTime = 0.22f;

        // BOTTOM DWELL - quiet time for the frame to damp before the next rise, and for the ball to
        // settle so the next cycle's tilt correction acts on a ball that is actually on the plate.
        // With these four numbers the cycle is 0.60s (1.7Hz) against the old 0.25s (4Hz), and it
        // contains one hard acceleration instead of two - about 79% fewer hard accelerations per
        // second. That drop, not the smaller hop, is the part that should stop the shaking.
        [SerializeField] private float _smallJugglingBottomDwellTime = 0.15f;

        // How long the bouncing phase lasts, in seconds. Converted to a cycle count against the
        // real cycle time (both strokes plus the firmware's 50ms margin), so changing the move time
        // above keeps this duration honest instead of silently rescaling it.
        [SerializeField] private float _smallJugglingBounceSeconds = 45f;

        // Control cycles spent settling before the bouncing starts, and the stepped descent after
        // the centring stage. At _balancingMoveTime each cycle is ~0.15s.
        [SerializeField] private int _smallJugglingSettleCycles = 15;
        [SerializeField] private int _smallJugglingDescentSteps = 4;
        [SerializeField] private int _smallJugglingDescentCyclesPerStep = 8;
        [SerializeField] private int _smallJugglingLandedCycles = 20;

        // The centring stage that runs after the bouncing stops: balance, no oscillation, until the
        // ball is actually settled on the target. Condition-based rather than a fixed count,
        // because how long a ball takes to come to rest depends on how it was moving when the
        // bouncing ended - see BalancingUntilSettledStrategy.
        //
        // All three conditions have to hold together for _smallJugglingCentredHoldCycles running:
        // near the target, slow, and down on the plate. The height term is what makes it wait for
        // the bouncing to actually die out - a ball at the apex of a bounce can otherwise sit right
        // over the target at near-zero vertical speed and look settled for an instant.
        //
        // 8mm of tolerance is comfortably inside the frame: at the 20mm base the camera sees about
        // +-30mm in X and +-42mm in Y at plate level.
        [SerializeField] private float _smallJugglingCentredToleranceMm = 8f;
        [SerializeField] private float _smallJugglingCentredSpeedMmPerSec = 30f;
        [SerializeField] private float _smallJugglingCentredHeightMm = 12f;
        [SerializeField] private int _smallJugglingCentredHoldCycles = 12;

        // Backstop so a ball that never quite settles cannot hold the program here forever and
        // starve the descent stages. ~22s at _balancingMoveTime.
        [SerializeField] private int _smallJugglingCentredMaxCycles = 150;

        // How far the plate rises for a "juggle" bounce, in mm above _balancingPlateHeight, and
        // how long that one move takes. Shared by SmallJugglingDemo and the first bounce stage of
        // FullJugglingDemo.
        //
        // MUST clear 1g, not stay under it - the opposite of the earlier "administrative move"
        // fix (RiseToTestHeight etc.), and that distinction is the whole story here. Bouncing()
        // sends the rise and the fall as two SEPARATE moves, and this firmware's motion profile
        // is a half-cosine ease that starts AND ends at rest within each one:
        //   x(t) = rise/2 * (1 - cos(pi t / moveTime))
        //   peak |acceleration| = pi^2 * rise / (2 * moveTime^2), at the START and END of each move
        // The ball stays in contact with the plate for as long as the plate's downward
        // deceleration never exceeds g - below that threshold there is nothing pulling the ball
        // away, so it just rides up and down like an elevator, in full contact the whole time.
        // That is exactly what 25mm/0.12s (0.87g) did: correctly gentle, and for that reason
        // incapable of ever producing a real bounce. The plate has to shed the ball, briefly,
        // right around the top of the rise, for it to look like juggling at all.
        //
        // 20mm/0.06s (2.79g commanded) DID separate the ball - confirmed - but it also produced
        // NaN rotation errors from InverseKinematics on some frames (a commanded height this
        // aggressive, ADDED to whatever tilt correction was in flight at the same instant, briefly
        // asked one arm for a Y position outside its physical reach - see the clamps now in
        // InverseKinematic.cs, which stop that from ever reaching a real motor as NaN, but the
        // clamped output is still not the height that was actually wanted). And it read as far too
        // violent - a "little height" oscillation was asked for instead.
        //
        // GetBallBouncing() runs this Bouncing() stage ALTERNATING with BouncingStrong() (own
        // untouched defaults: 30mm/0.08s... no, 30mm/0.1s = 1.51g), and BouncingStrong is the stage
        // that was ALREADY proven to separate the ball on its own back when FullJugglingDemo first
        // worked - Bouncing() does not need to ALSO clear 1g, and trying to make it do so just
        // compounded two energetic stages back to back. Its actual job in this pairing is to be
        // the gentle settle/reposition between BouncingStrong's hits, not a second hit.
        //
        // 8mm / 0.1s -> 3.95 m/s^2 = 0.40g - deliberately UNDER 1g, a small repositioning move with
        // no separation of its own, on the same 0.1s cadence as BouncingStrong for a smooth rhythm
        // instead of a sharp, jerky snap. If the overall demo still reads as too aggressive, the
        // stage actually worth softening next is BouncingStrong (lowPos/highPos on the
        // BouncingStrong(...) calls inside GetBallBouncing), not this one.
        [SerializeField] private float _jugglingBounceRiseMm = 8f;
        [SerializeField] private float _jugglingBounceMoveTime = 0.1f;

        // Plate height held while balancing, in metres above the working origin. Higher is not
        // just safer - on this rig raising the plate moves the ball AWAY from the camera, which
        // widens the visible patch of the plate (+-29mm in X at the origin, +-50mm at 50mm).
        [SerializeField] private float _balancingPlateHeight = 0.05f;

        // Where on the plate to hold the ball, in mm from centre.
        [SerializeField] private Vector2 _balancingTarget = Vector2.zero;

        // How long the ball may stay undetected before the strategies are disarmed. Without this
        // a lost ball simply froze the plate on its last command forever, with no way back.
        // Raised from 0.35s: during juggling the ball is deliberately airborne for ~0.15-0.2s a
        // bounce, and detection can legitimately drop a frame or two around the apex. 0.35s was
        // tight enough to abort on a perfectly healthy bounce. 1s still catches a genuinely lost
        // ball quickly while riding out the normal gaps.
        [SerializeField] private float _ballLostTimeout = 1f;

        // Where the plate parks after a lost-ball abort, in mm above the working origin.
        //
        // 0 = the working origin itself, which is the right answer now that the working origin is
        // Constants.OriginHeightOffset (20mm) above the mechanical dead position rather than the
        // 2mm it was when this field was introduced. Back then "origin" meant essentially flat on
        // the deck and a raised standing height was worth having; now the origin IS the raised
        // standing height, and parking anywhere above it just leaves the plate somewhere arbitrary.
        [SerializeField] private float _ballLostRecoveryHeightMm = 0f;
        [SerializeField] private float _ballLostRecoveryMoveTime = 0.3f;

        [Header("Camera -> plate axis mapping")]
        // Maps the ball position measured in CAMERA pixels onto the machine's tilt axes. Both tilt
        // controllers require, for the loop to push the ball back to centre rather than away:
        //     +XTilt must move the ball toward +x        (it raises the motor-1 corner)
        //     +YTilt must move the ball toward -y        (it raises the motor-3 corner)
        // which means camera +x has to be the motor-2 corner and camera +y the motor-3 corner.
        // Rotate the camera, mirror the image, or swap two motor connectors and that breaks - the
        // plate then tilts the wrong way and accelerates the ball off the plate. Rather than guess
        // which of the eight combinations is right, press C to measure it (TiltSignCheckRoutine).
        // Determined automatically the first time you arm the machine, by tilting the plate and
        // watching which way the ball actually rolls - see TiltSignCheckRoutine. These values are
        // only the fallback if that measurement cannot run, and are what it measured on this rig
        // on 2026-08-26: (cx, cy) -> (-cy, -cx). That is a REFLECTION, not a rotation
        // (determinant -1), which is what a portrait 480x640 sensor combined with the usual
        // OpenCV-to-Unity vertical flip produces. Both tilt controllers treat X and Y
        // independently, so a mirrored frame maps through cleanly.
        // swap = true is confirmed PHYSICALLY, not just by measurement: the same ceiling
        // photographed with a phone and with this camera shows the tile lines running vertically
        // in one and horizontally in the other, i.e. the image is a quarter turn out. That is also
        // why the sensor delivers a portrait 480x640 frame when 640x480 is requested.
        //
        // swap + exactly ONE invert is a true 90 degree rotation, which is what the photos show;
        // swap + zero or two inverts would be a rotation PLUS a mirror. invertY is the one chosen
        // because swap/false/true was also the most frequently measured result across the
        // TiltSign runs that completed. If the ball is still driven off the plate, tick
        // Invert Camera X as well - that is the rotation-plus-mirror case and the only other
        // candidate worth trying.
        //
        // Fixing this in software rather than rotating the camera is deliberate: a quarter turn
        // about the lens axis changes neither the field of view nor the distance to the plate, so
        // CameraFOVInDegrees and BallHeightAtOrigin stay valid. Moving the mount would invalidate
        // both and mean redoing the two-point height calibration.
        [SerializeField] private bool _swapCameraAxes = true;
        [SerializeField] private bool _invertCameraX = false;
        [SerializeField] private bool _invertCameraY = true;

        // Run the tilt-sign measurement automatically when the machine is first armed.
        //
        // Off by default: the mapping is now known from the flags above, and the measurement needs
        // the ball to stay on the plate for ~15s, which it will not do without a rim. Press C to
        // run it deliberately once the ball can be kept on the plate.
        [SerializeField] private bool _autoCalibrateAxisMapping = false;

        // Tilt magnitudes tried in order until the ball actually responds. Starting small keeps
        // the ball near the centre; escalating means a stiff plate reports how much tilt it needs
        // instead of just failing. Capped by Constants.MaxTiltAngle (5 deg).
        [SerializeField] private float[] _tiltSignCheckLadder = {2f, 3f, 4f, 5f};

        // Upper limit on one leg of the bang-bang profile. The actual leg length is worked out
        // per tilt angle from _ballTravelBudget - see PhaseFor().
        [SerializeField] private float _tiltSignCheckPhase = 0.35f;

        // How far the ball is allowed to travel during a test sweep, in mm. Peak excursion of the
        // profile is a*T^2, so a fixed leg length sends the ball 63mm at 5 deg - straight off the
        // plate, which is exactly what happened when the 5 deg buttons were tried by hand.
        // Choosing T = sqrt(budget / accel) per angle keeps the travel constant instead, so every
        // tilt on the ladder is equally safe and only the measurement time changes.
        //
        // 8mm, not 25mm: the ball's centre has only about +-8mm of clear frame at the origin
        // height and +-28mm at the balancing height before the ball itself touches the edge and
        // the traced centre goes wrong. 25mm was sending it right up against that limit, which is
        // where the measurements stopped meaning anything.
        [SerializeField] private float _ballTravelBudget = 8f;

        // Time allowed for the one big move at the start of a test: the plate rising from the
        // working origin (Constants.OriginHeightOffset above the mechanical dead position) to the
        // balancing height. The tilt moves that follow are only millimetres
        // at the plate corners, so their hardcoded 0.15s is harmless - but this one is a 48mm rise,
        // and at 0.15s the plate peaks at 1.07 g. On the deceleration half it pulls DOWN at that
        // rate, dropping away faster than the ball can fall, and launches it. 0.6s peaks at 0.07 g.
        [SerializeField] private float _testHeightMoveTime = 0.6f;

        // A sweep must start with the ball near the middle. Starting it 20mm out and then asking
        // for 8mm of travel puts it at the edge, and the run is wasted - or the ball is lost and
        // every reading after it is junk. Checked before anything moves.
        [SerializeField] private float _requiredStartRadiusMm = 10f;

        // Window over which the ball's drift is measured once the tilt has had time to act.
        [SerializeField] private float _tiltSignCheckWindow = 0.15f;

        // Below this the drift is indistinguishable from detection noise and the result is not
        // trusted. Roughly 13mm is expected at 2.5 deg, so 4mm is a generous floor.
        [SerializeField] private float _tiltSignCheckMinDrift = 4f;

        // Each axis must start from rest, or the +leg inherits speed from whatever came before and
        // the two legs come out lopsided. Wait until the ball drifts less than this per window.
        [SerializeField] private float _ballSettleDrift = 4f;
        [SerializeField] private float _ballSettleTimeout = 1.5f;

        [Header("Plate response check (press P)")]
        // Commanded tilts swept by the plate-response check. It reports how much of each the plate
        // ACTUALLY delivers, using the ball as an inclinometer - no calipers needed.
        [SerializeField] private float[] _plateCheckLadder = {1f, 2f, 3f, 5f};

        // The plate takes _machineController's move time to reach a commanded tilt, so the ball is
        // not accelerating for the whole hold. Subtracted from the acceleration window. Roughly
        // half the 0.15s move time for a sine velocity profile.
        [SerializeField] private float _tiltRampAllowance = 0.075f;

        // Time given to each balancing correction. This IS the loop delay (plus the 50ms
        // microcontroller margin), and Constants.k_p / k_d were derived against 0.1s - shortening
        // it buys phase margin, but the gains should be re-derived if you change it much.
        [SerializeField] private float _balancingMoveTime = 0.1f;

        private BallData _ballData;
        private int _currentStrategyIndex;
        private bool _isBallPositionLoggingEnabled;
        private bool _hasWarnedAboutOrigin;
        private float _ballLostTimer;

        // Ball position in raw camera axes (mm), BEFORE the mapping above is applied. The sign
        // check reads this so its measurement cannot be biased by the mapping it is trying to
        // determine. Vector2.zero when no ball was seen this frame.
        // How much clear frame the ball must have around it for its centre to be trustworthy.
        private const float BallEdgeMarginPixels = 6f;

        private Vector2 _lastRawBallPosition;
        private bool _hasRawBallPosition;
        private bool _ballFullyVisible;

        // ONE routine may command the plate at a time. Arm, the tilt-sign check and the plate
        // response check all drive the plate AND measure the ball; running two at once means each
        // is measuring the other's tilts, which produces confident-looking nonsense - plant gains
        // scattered from 10 to 330 mm/s^2/deg and "delivered" figures from 20% to 500%.
        private Coroutine _machineRoutine;
        private string _machineRoutineName;

        private bool _axisMappingCalibrated;

        // Coroutines cannot return values, so the measurement steps report through these.
        private Vector2 _lastDrift;
        private bool _lastDriftValid;
        private Vector2 _lastDriftPlus;
        private Vector2 _lastDriftMinus;
        private Vector2 _lastResponse;
        private bool _lastResponseValid;
        private float _lastEffectiveAccelTime;

        private ReactiveProperty<bool> _isExecuteControlStrategies = new ReactiveProperty<bool>();
        public IObservable<bool> OnExecutingControlStrategies => _isExecuteControlStrategies;

        private ReplaySubject<int> _onCheckPointPassedSubject = new ReplaySubject<int>();
        public IObservable<int> OnCheckPointPassed => _onCheckPointPassedSubject;

        private List<IBallControlStrategy> _strategies = new List<IBallControlStrategy>();

        private void Awake()
        {
            _gradientDescentViewX.GradientDescent = _gradientDescentX;
            _gradientDescentViewY.GradientDescent = _gradientDescentY;
            _gradientDescentViewZ.GradientDescent = _gradientDescentZ;

            AnalyticalTiltController.Instance.TargetCrossVisualizer = _targetCrossVisualizer;
            PIDTiltController.Instance.TargetCrossVisualizer = _targetCrossVisualizer;

            _onCheckPointPassedSubject.OnNext(0);
        }

        private void Start()
        {
            _ballData = new BallData(
                _ballDataDebugView,
                _predictedPositionVisualizer,
                _gradientDescentX,
                _gradientDescentY,
                _gradientDescentZ);

            switch (_strategyProgram)
            {
                case StrategyProgram.BalancingOnly:
                    BuildBalancingOnlyProgram();
                    break;

                case StrategyProgram.SmallJugglingDemo:
                    BuildSmallJugglingDemoProgram();
                    break;

                case StrategyProgram.FullJugglingDemo:
                    BuildFullJugglingDemo();
                    break;
            }

            Debug.Log("[ImageProcessing] Strategy program: " + _strategyProgram +
                      " (" + _strategies.Count + " stage(s)). Press Space to arm.");
        }

        /// <summary>
        /// Bring-up program: no throwing, no bouncing. Wait until the ball is seen resting on the
        /// plate, raise the plate to the balancing height, then hold the ball at the target with
        /// PD tilt corrections indefinitely. If the machine cannot do this, none of the bouncing
        /// stages in the full demo can work either - so this is the thing to get right first.
        /// </summary>
        private void BuildBalancingOnlyProgram()
        {
            _strategies.Add(BallControlStrategyFactory.GoToWhenBallOnPlate(_balancingPlateHeight));

            _strategies.Add(BallControlStrategyFactory.Balancing(
                _balancingPlateHeight,
                // Never completes: this single stage IS the whole program.
                int.MaxValue,
                _balancingTarget,
                PIDTiltController.Instance,
                _balancingMoveTime,
                action: () => _machineStateView.Set("Balancing",
                    MachineStateView.TiltControlType.PIDTiltController)));
        }

        /// <summary>
        /// A small, self-contained juggling demo for showing the detection + leveling pipeline
        /// doing something more than holding still, without the risk the full demo's early
        /// BouncingStrong stage carries. Settles the ball at centre first - if that does not hold,
        /// the bounce stage is not going to do any better - then runs a bounded number of gentle
        /// bounces, and lands. Re-arm with Space to run it again.
        /// </summary>
        private void BuildSmallJugglingDemoProgram()
        {
            var baseHeight = _smallJugglingBaseHeightMm / 1000f;
            var topHeight = baseHeight + _smallJugglingOscillationMm / 1000f;

            // 1 --------------------------------------------------- wait for the ball, then rise
            _strategies.Add(BallControlStrategyFactory.GoToWhenBallOnPlate(baseHeight));

            // 2 ------------------------------------------- settle and centre before any bouncing
            // Worth its own stage: the oscillation below aims each hit using where the ball is
            // going, so starting it with the ball already drifting just launches the drift.
            _strategies.Add(BallControlStrategyFactory.Balancing(
                baseHeight,
                _smallJugglingSettleCycles,
                _balancingTarget,
                PIDTiltController.Instance,
                _balancingMoveTime,
                action: () => _machineStateView.Set("Settling",
                    MachineStateView.TiltControlType.PIDTiltController)));

            // 3 ------------------------------------------------------------------- the juggling
            // Bouncing() sends the up-stroke WITH the tilt correction applied and the down-stroke
            // level, so the ball is being aimed back toward the target on every single bounce -
            // this one stage is both the oscillation and the balancing, not two competing things.
            //
            // AnalyticalTiltController, not PID: PID only knows where the ball IS, which is the
            // wrong question for a ball that spends part of each cycle in the air. The analytical
            // one uses BallData.AirborneTime and the predicted bounce velocity to aim at where the
            // ball will LAND. (AirborneTime is internally clamped to >=0.1s, so the very first
            // bounce - before any flight has been measured - cannot divide by zero.)
            // Cycle time is all four phases plus the 50ms microcontroller margin
            // MachineController.SendInstructions adds - counted FOUR times, because the phases go
            // out as four separate sends so the tilt can be recomputed on each one (see
            // RhythmicBouncing). That is what actually paces the rhythm, so deriving the count from
            // it keeps the phase at the requested number of seconds whatever the four times are.
            var bounceCycleSeconds = _smallJugglingRiseTime + _smallJugglingTopDwellTime
                                     + _smallJugglingFallTime + _smallJugglingBottomDwellTime
                                     + 4f * 0.05f;
            var bounceCycles = Mathf.Max(1, Mathf.RoundToInt(_smallJugglingBounceSeconds / bounceCycleSeconds));

            // PID, not Analytical: the ball has to be steered by where it IS and how fast it is
            // moving, which is what keeps it on the centre through the bounce. AnalyticalTiltController
            // models a paddle redirecting a ball in real flight and saturates the tilt on this
            // gentle ~3mm hop - see the note on RhythmicBouncing. Same controller and same target as
            // the balancing stages, so the ball is held to the same place throughout the program.
            _strategies.Add(BallControlStrategyFactory.RhythmicBouncing(
                bounceCycles,
                PIDTiltController.Instance,
                _balancingTarget,
                lowPos: baseHeight,
                highPos: topHeight,
                riseTime: _smallJugglingRiseTime,
                topDwellTime: _smallJugglingTopDwellTime,
                fallTime: _smallJugglingFallTime,
                bottomDwellTime: _smallJugglingBottomDwellTime,
                action: () => _machineStateView.Set("Juggling",
                    MachineStateView.TiltControlType.PIDTiltController)));

            // 4 ------------------------------------------- oscillation stops, balancing continues
            // The plate now holds one height and only tilts, so the ball drops out of its bounce
            // and is steered to the centre. Ends when the ball is genuinely settled there rather
            // than after a set time, so the descent below always starts from a ball at rest.
            _strategies.Add(BallControlStrategyFactory.BalancingUntilSettled(
                baseHeight,
                _balancingTarget,
                PIDTiltController.Instance,
                _smallJugglingCentredToleranceMm,
                _smallJugglingCentredSpeedMmPerSec,
                _smallJugglingCentredHeightMm,
                _smallJugglingCentredHoldCycles,
                _smallJugglingCentredMaxCycles,
                _balancingMoveTime,
                action: () => _machineStateView.Set("Centering",
                    MachineStateView.TiltControlType.PIDTiltController)));

            // 5 ------------------------------------------------- gradual descent to the origin
            // Stepped, with a Balancing stage per step, so the controller keeps correcting the
            // ball the whole way down instead of going open-loop for the descent. The steps are
            // small (baseHeight/steps = 5mm at the defaults) and run at _balancingMoveTime, which
            // keeps every one of them far below 1g - the opposite of what stage 3 is deliberately
            // doing, so the descent cannot accidentally toss the ball it just caught.
            for (int step = _smallJugglingDescentSteps - 1; step >= 1; step--)
            {
                var stepHeight = baseHeight * step / _smallJugglingDescentSteps;
                var isFirstStep = step == _smallJugglingDescentSteps - 1;

                _strategies.Add(BallControlStrategyFactory.Balancing(
                    stepHeight,
                    _smallJugglingDescentCyclesPerStep,
                    _balancingTarget,
                    PIDTiltController.Instance,
                    _balancingMoveTime,
                    action: isFirstStep
                        ? () => _machineStateView.Set("Descending",
                            MachineStateView.TiltControlType.PIDTiltController)
                        : (Action)null));
            }

            // 6 ------------------------------------- arrive at the origin and hold, still balancing
            _strategies.Add(BallControlStrategyFactory.Balancing(
                0f,
                _smallJugglingLandedCycles,
                _balancingTarget,
                PIDTiltController.Instance,
                _balancingMoveTime,
                action: () => _machineStateView.Set("Landed",
                    MachineStateView.TiltControlType.PIDTiltController)));
        }

        private void BuildFullJugglingDemo()
        {
            _strategies.Add(BallControlStrategyFactory.GoTo(0.01f));
            _strategies.Add(BallControlStrategyFactory.GoTo(0.05f));

            _strategies.Add(BallControlStrategyFactory.GoToWhenBallOnPlate(0.01f));
            _strategies.Add(BallControlStrategyFactory.GoToWhenBallOnPlate(0.05f));

            GetBallBouncing(() =>
            {
                _onCheckPointPassedSubject.OnNext(1);
                _machineStateView.Set("Get Ball Bouncing", MachineStateView.TiltControlType.PIDTiltController);
            });
            
            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(20, AnalyticalTiltController.Instance,
                action: () => _machineStateView.Set("Two Step Bouncing",
                        MachineStateView.TiltControlType.AnalyticalTiltControl)));

            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(40, AnalyticalTiltController.Instance,
                action: () => _onCheckPointPassedSubject.OnNext(2)));
            
            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(20, AnalyticalTiltController.Instance,
                action: () => _onCheckPointPassedSubject.OnNext(3)));
            
            CircleBouncing(10, () => _machineStateView.Set("Circle Bouncing",
                MachineStateView.TiltControlType.AnalyticalTiltControl));

            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(20, AnalyticalTiltController.Instance,
                new Vector2(40f, 0f), action: () => _machineStateView.Set("Two Step Bouncing",
                    MachineStateView.TiltControlType.AnalyticalTiltControl)));
            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(20, AnalyticalTiltController.Instance,
                new Vector2(0f, 0f)));
            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(20, AnalyticalTiltController.Instance,
                new Vector2(-40f, 0f)));
            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(20, AnalyticalTiltController.Instance,
                new Vector2(0f, 0f)));
            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(20, AnalyticalTiltController.Instance,
                new Vector2(40f, 0f)));
            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(20, AnalyticalTiltController.Instance,
                new Vector2(0f, 0f)));
            _strategies.Add(BallControlStrategyFactory.TwoStepBouncing(20, AnalyticalTiltController.Instance,
                new Vector2(-40f, 0f)));

            for (int i = 0; i < 5; i++)
            {
                _strategies.Add(
                    BallControlStrategyFactory.Bouncing(5, AnalyticalTiltController.Instance));
                _strategies.Add(
                    BallControlStrategyFactory.BouncingStrong(1, AnalyticalTiltController.Instance));
                _strategies.Add(BallControlStrategyFactory.Balancing(0.05f, 8, Vector2.zero,
                    AnalyticalTiltController.Instance));
            }

            _strategies.Add(BallControlStrategyFactory.GoTo(0.01f));
            _strategies.Add(BallControlStrategyFactory.GoTo(0.08f));
            _strategies.Add(BallControlStrategyFactory.GoTo(0.05f));

            GetBallBouncing();

            _strategies.Add(BallControlStrategyFactory.Bouncing(20, AnalyticalTiltController.Instance));

            for (int i = 0; i < 5; i++)
            {
                _strategies.Add(
                    BallControlStrategyFactory.Bouncing(5, AnalyticalTiltController.Instance));
                _strategies.Add(
                    BallControlStrategyFactory.BouncingStrong(1, AnalyticalTiltController.Instance));
                _strategies.Add(
                    BallControlStrategyFactory.Balancing(0.05f, 8, Vector2.zero, AnalyticalTiltController.Instance));
            }

            _strategies.Add(BallControlStrategyFactory.GoTo(0.01f));
        }

        // extraCycles=4 (the original hardcoded loop count) keeps FullJugglingDemo's own call
        // below - which passes no explicit value - behaving exactly as it did before this became a
        // parameter, so nothing about the demo that is already confirmed working changes.
        //
        // Uses AnalyticalTiltController, not PIDTiltController - "the ball is not balanced to hit
        // the center while juggling" is a controller mismatch, not a gain problem. PIDTiltController
        // only reacts to the ball's CURRENT position/velocity, which is the right tool for
        // continuous-contact balancing but not for a bouncing ball: it has no way to account for
        // where the ball will actually LAND next, so its correction is only ever chasing where the
        // ball WAS. AnalyticalTiltController is the predictive one - it already uses
        // BallData.AirborneTime and CalculatedOnBounceDownwardsVelocity to aim the NEXT bounce at
        // the target, which is exactly why FullJugglingDemo's own later stages (TwoStepBouncing,
        // StepBouncing_Up/_Down, CircleBouncing) all use it instead of PID. GetBallBouncing() was
        // the one place still using PID for a bouncing ball - this brings it in line with the rest
        // of the choreography, for both programs that call it.
        private void GetBallBouncing(Action action = null, int extraCycles = 4)
        {
            // Only the Bouncing() stages are retuned here to the visible amplitude - the
            // BouncingStrong() stages already had working, deliberately larger parameters of their
            // own (lowPos/highPos were never broken on that one) and are left as originally tuned.
            var jugglingHigh = _balancingPlateHeight + _jugglingBounceRiseMm / 1000f;

            _strategies.Add(
                BallControlStrategyFactory.Bouncing(5, AnalyticalTiltController.Instance,
                    lowPos: _balancingPlateHeight, highPos: jugglingHigh,
                    moveTime: _jugglingBounceMoveTime, action: action));
            _strategies.Add(
                BallControlStrategyFactory.BouncingStrong(1, AnalyticalTiltController.Instance));

            for (int i = 0; i < extraCycles; i++)
            {
                _strategies.Add(BallControlStrategyFactory.Bouncing(5, AnalyticalTiltController.Instance,
                    lowPos: _balancingPlateHeight, highPos: jugglingHigh,
                    moveTime: _jugglingBounceMoveTime));
                _strategies.Add(BallControlStrategyFactory.BouncingStrong(1, AnalyticalTiltController.Instance));
            }
        }

        private void CircleBouncing(int iterations = 1, Action action = null)
        {
            var angle = 0f;
            var radius = 30f;
            var numberOfSlices = 15;
            var target = Vector2.zero;

            for (int j = 0; j < iterations; j++)
            {
                for (int i = 0; i < numberOfSlices; i++)
                {
                    angle = Mathf.PI * 2 * i / numberOfSlices;
                    target.x = Mathf.Cos(angle) * radius;
                    target.y = Mathf.Sin(angle) * radius;
                    _strategies.Add(
                        BallControlStrategyFactory.StepBouncing_Down(AnalyticalTiltController.Instance, target,
                            action: action));
                    _strategies.Add(
                        BallControlStrategyFactory.StepBouncing_Up(AnalyticalTiltController.Instance, target));
                }
            }
        }

        private void Update()
        {
            if (Input.GetKeyDown(KeyCode.Space))
            {
                if (_isExecuteControlStrategies.Value)
                {
                    Disarm();
                }
                else
                {
                    TryStartMachineRoutine("Arm", ArmRoutine());
                }
            }

            // Work out which motors are paired, by trying every possibility.
            if (Input.GetKeyDown(KeyCode.R))
            {
                TryStartMachineRoutine("MotorPairing", MotorPairingSearchRoutine());
            }

            // Measure what tilt the plate physically delivers, using the ball as the instrument.
            if (Input.GetKeyDown(KeyCode.P))
            {
                TryStartMachineRoutine("PlateCheck", PlateResponseRoutine());
            }

            // Force the axis mapping to be re-measured, e.g. after moving the camera.
            if (Input.GetKeyDown(KeyCode.C))
            {
                if (TryStartMachineRoutine("TiltSign", TiltSignCheckRoutine()))
                {
                    _axisMappingCalibrated = false;
                }
            }

            if (Input.GetKeyDown(KeyCode.L))
            {
                _isBallPositionLoggingEnabled = !_isBallPositionLoggingEnabled;
                Debug.Log($"Ball position logging {(_isBallPositionLoggingEnabled ? "enabled" : "disabled")}");
            }

            var ballRadiusAndPosition = _cameraPlugin.UpdateImageProcessing();

            if (_isBallPositionLoggingEnabled)
            {
                Debug.Log($"Ball r, x, y :{ballRadiusAndPosition.Radius}, {ballRadiusAndPosition.PositionX}, {ballRadiusAndPosition.PositionY}");
            }

            var height = FOVCalculations.RadiusToDistance(ballRadiusAndPosition.Radius);

            if (height < float.MaxValue)
            {
                if (Input.GetKeyDown(KeyCode.I))
                {
                    LogBallCalibrationSample("origin", ballRadiusAndPosition, height);
                }
                else if (Input.GetKeyDown(KeyCode.X))
                {
                    LogBallCalibrationSample("max_distance", ballRadiusAndPosition, height);
                }
            }
            else if (Input.GetKeyDown(KeyCode.I) || Input.GetKeyDown(KeyCode.X))
            {
                Debug.LogWarning("Cannot log calibration sample: ball not detected in current frame.");
            }

            if (!_isExecuteControlStrategies.Value)
            {
                foreach (var strategy in _strategies)
                {
                    strategy.Reset();
                }

                _currentStrategyIndex = 0;
            }

            // Nothing downstream of here is meaningful until the plate has been parked at the
            // working origin (Constants.OriginHeightOffset above the mechanical dead position):
            // FOVCalculations reports every ball height relative to the plate-at-origin plane, so
            // samples taken while the plate is still travelling would train the gradient descents
            // - and the controllers - against the wrong reference.
            if (!_machineController.IsAtWorkingOrigin)
            {
                if (!_hasWarnedAboutOrigin)
                {
                    _hasWarnedAboutOrigin = true;
                    Debug.Log("Waiting for the plate to reach the working origin before starting detection.");
                }

                // The plate is moving under our own command, so a missing ball here means nothing.
                _ballLostTimer = 0f;
                return;
            }

            if (height >= float.MaxValue)
            {
                // Couldn't find the ball in the image. Everything below this point needs a
                // position, so the frame is unusable - but if it stays unusable while the
                // strategies are armed, the plate would otherwise sit frozen on its last command
                // indefinitely, which is exactly what happens when a ball gets thrown clear.
                _ballLostTimer += Time.deltaTime;
                _hasRawBallPosition = false;
                _ballFullyVisible = false;

                if (_isExecuteControlStrategies.Value && _ballLostTimer >= _ballLostTimeout)
                {
                    AbortOnBallLost();
                }

                return;
            }

            _ballLostTimer = 0f;

            _lastRawBallPosition = new Vector2(
                FOVCalculations.PixelPositionToDistanceFromCenter(ballRadiusAndPosition.PositionX, height),
                FOVCalculations.PixelPositionToDistanceFromCenter(ballRadiusAndPosition.PositionY, height));
            _hasRawBallPosition = true;

            // Is the WHOLE ball inside the frame, or is the edge cutting a piece off it?
            //
            // This matters far more here than on a normal rig because the camera sits ~70mm from a
            // 40mm ball, so the ball spans 338 of the 480 pixels and its centre has only about
            // +-8mm of room at the origin height (+-28mm at the balancing height) before the ball
            // touches the frame edge. A clipped ball traces a CRESCENT, and the border tracer then
            // reports a centre displaced INWARD - the same direction every time, whatever tilt was
            // commanded. That is indistinguishable from a real response and it is almost certainly
            // what produced the tilt-axis readings of 140-169 degrees where 90 was expected.
            _ballFullyVisible =
                Mathf.Abs(ballRadiusAndPosition.PositionX) + ballRadiusAndPosition.Radius
                    < Constants.FrameWidth * 0.5f - BallEdgeMarginPixels &&
                Mathf.Abs(ballRadiusAndPosition.PositionY) + ballRadiusAndPosition.Radius
                    < Constants.FrameHeight * 0.5f - BallEdgeMarginPixels;

            // Everything downstream - gradient descents, BallData, the visualisers, both tilt
            // controllers - works in machine axes, so the mapping is applied once, here.
            var ballPosition = ToPlateAxes(_lastRawBallPosition);

            var ballPosX = ballPosition.x;
            _gradientDescentX.Hypothesis.SetTheta_0To(ballPosX);
            _gradientDescentX.AddTrainingSet(new TrainingSet(0f, ballPosX));
            _gradientDescentX.UpdateHypothesis();

            var ballPosY = ballPosition.y;
            _gradientDescentY.Hypothesis.SetTheta_0To(ballPosY);
            _gradientDescentY.AddTrainingSet(new TrainingSet(0f, ballPosY));
            _gradientDescentY.UpdateHypothesis();

            _gradientDescentZ.Hypothesis.SetTheta_0To(height);
            _gradientDescentZ.AddTrainingSet(new TrainingSet(0f, height));
            _gradientDescentZ.UpdateHypothesis();

            _ballData.UpdateData(
                new Vector3(
                    _gradientDescentX.Hypothesis.Parameters.Theta_0,
                    _gradientDescentY.Hypothesis.Parameters.Theta_0,
                    height),
                new Vector3(
                    _gradientDescentX.Hypothesis.Parameters.Theta_1,
                    _gradientDescentY.Hypothesis.Parameters.Theta_1,
                    _gradientDescentZ.Hypothesis.Parameters.Theta_1
                ));

            _ballPositionVisualizer.VisualizePositionPoint(_ballData.CurrentUnityPositionVector);
            _currentPositionCrossVisualizer.UpdateCrossPosition(
                new Vector2(_ballData.CurrentPositionVector.x, _ballData.CurrentPositionVector.y));

            if (_machineController.IsReadyForNextInstruction && _isExecuteControlStrategies.Value)
            {
                var isRequestingNextStrategy =
                    _strategies[_currentStrategyIndex].Execute(_ballData, _machineController);

                if (isRequestingNextStrategy)
                {
                    _strategies[_currentStrategyIndex].Reset();

                    if (_currentStrategyIndex < _strategies.Count - 1)
                    {
                        _currentStrategyIndex++;

                        _predictedPositionVisualizer
                            .SetActive(_strategies[_currentStrategyIndex].UsesBallPositionPrediction);

                        _strategies[_currentStrategyIndex].OnStrategyExecutionStart?.Invoke();
                    }
                }
            }
        }

        /// <summary>
        /// Starts a routine that both commands the plate and measures the ball, but only if no
        /// other such routine is already running. Refusing is the whole point: overlapping runs
        /// contaminate each other's measurements and the results look plausible but are junk.
        /// </summary>
        private bool TryStartMachineRoutine(string name, IEnumerator routine)
        {
            if (_machineRoutine != null)
            {
                Debug.LogWarning($"[Calibration] {_machineRoutineName} is still running - ignoring " +
                                 $"{name}. Two routines tilting the plate at once make every " +
                                 "measurement meaningless. Wait for it to finish.");
                return false;
            }

            _machineRoutineName = name;
            _machineRoutine = StartCoroutine(RunExclusively(routine));
            return true;
        }

        private IEnumerator RunExclusively(IEnumerator routine)
        {
            yield return routine;

            _machineRoutine = null;
            _machineRoutineName = null;
        }

        /// <summary>
        /// Everything that has to be true before the machine may act on ball data, done for you:
        /// the right image mode, the plate at the working origin, and - the first time only - the
        /// camera-to-plate axis mapping measured from the ball's actual response to a test tilt.
        /// </summary>
        private IEnumerator ArmRoutine()
        {
            EnsureDetectionImageMode();

            yield return new WaitUntil(() => _machineController.IsAtWorkingOrigin);

            if (_autoCalibrateAxisMapping && !_axisMappingCalibrated)
            {
                Debug.Log("[Arm] First arm this session - measuring the camera-to-plate axis " +
                          "mapping before handing the machine the ball. Keep the ball on the plate.");

                yield return TiltSignCheckRoutine();

                if (!_axisMappingCalibrated)
                {
                    Debug.LogWarning("[Arm] Axis mapping could not be measured, so the machine was " +
                                     "NOT armed - it would have driven the ball off the plate if the " +
                                     "mapping were wrong. Re-centre the ball and press Space again.");
                    yield break;
                }
            }

            _ballLostTimer = 0f;
            _isExecuteControlStrategies.Value = true;

            Debug.Log("[Arm] Balancing. The plate lifts the side the ball is rolling toward and " +
                      "walks it back to the target.");

        }

        private void Disarm()
        {
            if (_machineRoutine != null)
            {
                StopCoroutine(_machineRoutine);
                _machineRoutine = null;
                _machineRoutineName = null;
            }

            _isExecuteControlStrategies.Value = false;
            _ballLostTimer = 0f;
        }

        private Vector2 ToPlateAxes(Vector2 cameraPosition)
        {
            var p = _swapCameraAxes
                ? new Vector2(cameraPosition.y, cameraPosition.x)
                : cameraPosition;

            if (_invertCameraX)
            {
                p.x = -p.x;
            }

            if (_invertCameraY)
            {
                p.y = -p.y;
            }

            return p;
        }

        /// <summary>
        /// Determines the camera-to-plate axis mapping by measurement instead of by guesswork, and
        /// on the way measures how much tilt the machine actually needs before the ball responds
        /// at all. Works up a ladder of tilt angles and stops at the first one that produces a
        /// readable response, so a stiff or backlashed plate reports a number instead of failing.
        /// </summary>
        private IEnumerator TiltSignCheckRoutine()
        {
            _isExecuteControlStrategies.Value = false;

            if (!BallIsReadyToMeasure("TiltSign"))
            {
                yield break;
            }

            yield return RiseToTestHeight();

            var response = new Vector2[2];
            var solvedAt = 0f;
            var ballLost = false;

            foreach (var d in _tiltSignCheckLadder)
            {
                Debug.Log($"[TiltSign] Trying +-{d} deg. Keep the ball near the centre of the plate.");

                var usable = true;

                for (int axis = 0; axis < 2 && usable; axis++)
                {
                    var name = axis == 0 ? "X" : "Y";

                    yield return MeasureAxisResponse(axis, d);

                    if (!_lastResponseValid)
                    {
                        Debug.LogWarning($"[TiltSign] Lost the ball during the {name} sweep. Put it " +
                                         "back near the centre and press C again.");
                        ballLost = true;
                        usable = false;
                        break;
                    }

                    Debug.Log($"[TiltSign] {name} at +-{d} deg: ball drifted " +
                              $"({_lastDriftPlus.x:0.0}, {_lastDriftPlus.y:0.0}) mm one way and " +
                              $"({_lastDriftMinus.x:0.0}, {_lastDriftMinus.y:0.0}) mm the other in " +
                              $"{_tiltSignCheckWindow:0.00}s. Difference " +
                              $"({_lastResponse.x:0.0}, {_lastResponse.y:0.0}) mm " +
                              $"= {_lastResponse.magnitude:0.0} mm.");

                    if (_lastResponse.magnitude < _tiltSignCheckMinDrift)
                    {
                        usable = false;
                        break;
                    }

                    response[axis] = _lastResponse;
                }

                if (ballLost)
                {
                    yield break;
                }

                if (usable)
                {
                    solvedAt = d;
                    break;
                }

                Debug.LogWarning($"[TiltSign] The ball barely moved at {d} deg - the plate is not " +
                                 "delivering that tilt. Trying a larger one.");
            }

            if (solvedAt <= 0f)
            {
                ReportNoTiltResponse();
                yield break;
            }

            Debug.Log($"[TiltSign] Ball responds from {solvedAt} deg of commanded tilt. " +
                      (solvedAt <= 2.5f
                          ? "That is healthy."
                          : $"That is a large deadband - the balancing loop only ever commands about " +
                            $"{Constants.k_p * 30f:0.0} deg for a ball 30mm off centre, so it will " +
                            "struggle until the arm play is taken out."));

            ReportTiltSignCheck(response[0], response[1]);
        }

        /// <summary>
        /// Leg length for a given commanded tilt, sized so the ball travels _ballTravelBudget mm
        /// and no further, whatever the angle. Capped above by _tiltSignCheckPhase and below by
        /// the measurement window, so the drift sample always fits inside the leg.
        /// </summary>
        private float PhaseFor(float degrees)
        {
            var accel = Mathf.Max(BallAccelPerDegree * Mathf.Abs(degrees), 1f);
            var ideal = Mathf.Sqrt(Mathf.Max(_ballTravelBudget, 1f) / accel);

            return Mathf.Clamp(ideal, _tiltSignCheckWindow + 0.05f, _tiltSignCheckPhase);
        }

        // A ball rolling without slipping on a plate tilted by theta accelerates at
        // c*g*sin(theta) with c = 3/5 for a thin spherical shell (a ping-pong ball). At small
        // angles that is 102.7 mm/s^2 per degree - which makes the ball a usable inclinometer.
        private const float BallAccelPerDegree = 102.7f;

        private static float DegreesFromAccel(float accel)
        {
            return accel / BallAccelPerDegree;
        }

        /// <summary>
        /// Measures how much tilt the plate ACTUALLY delivers for a given commanded tilt, by timing
        /// the ball's acceleration. This replaces measuring the plate with calipers: the ball is
        /// the instrument. Reports the delivered fraction per axis and the plate's static slope.
        ///
        /// Caveat worth knowing: the absolute degrees assume the ball rolls without slipping. The
        /// DELIVERED FRACTION is the trustworthy number - it is a ratio, so the rolling constant
        /// and the timing allowance largely cancel out of it.
        /// </summary>
        private IEnumerator PlateResponseRoutine()
        {
            _isExecuteControlStrategies.Value = false;

            var levelPhase = PhaseFor(1f);
            var levelAccelerate = levelPhase - _tiltSignCheckWindow;
            var levelEffective =
                Mathf.Max(levelAccelerate + _tiltSignCheckWindow * 0.5f - _tiltRampAllowance, 0.02f);

            Debug.Log("[PlateCheck] Measuring what tilt the plate actually delivers, using the ball " +
                      "as the inclinometer. Keep the ball near the centre of the plate. This takes " +
                      "about a minute.");

            if (!BallIsReadyToMeasure("PlateCheck"))
            {
                yield break;
            }

            yield return RiseToTestHeight();

            // --- static slope: how far off level the plate sits with zero tilt commanded --------
            yield return SettleBall();
            yield return TiltAndMeasureDrift(0, 0f, levelAccelerate);

            if (_lastDriftValid)
            {
                var aLevel = (_lastDrift.magnitude / _tiltSignCheckWindow) / levelEffective;
                Debug.Log($"[PlateCheck] Commanded LEVEL: the ball still accelerates {aLevel:0} " +
                          $"mm/s^2, so the plate sits about {DegreesFromAccel(aLevel):0.00} deg off " +
                          "level. Anything past ~0.3 deg will bias the balancing loop.");
            }

            // --- delivered tilt, per axis ------------------------------------------------------
            var plantGains = new List<float>();

            for (int axis = 0; axis < 2; axis++)
            {
                var name = axis == 0 ? "X" : "Y";
                float sumProduct = 0f;
                float sumSquares = 0f;

                // Least squares of ball acceleration against COMMANDED tilt. The slope is the
                // plant gain the controller actually faces - it already contains the plate's
                // transmission loss and the ball's rolling constant, so no assumption about
                // either is needed to tune against it. The intercept separates a genuine
                // backlash deadband (crosses zero at a positive tilt) from a static slope.
                var rungGains = new List<float>();

                foreach (var d in _plateCheckLadder)
                {
                    yield return MeasureAxisResponse(axis, d);

                    if (!_lastResponseValid)
                    {
                        Debug.LogWarning($"[PlateCheck] Lost the ball during the {name} sweep at " +
                                         $"{d} deg. Re-centre it and press P again.");
                        yield break;
                    }

                    // _lastResponse is the velocity difference between the two legs times the
                    // window, so dividing by the window and then by the combined acceleration time
                    // gives the ball's acceleration under 1x the commanded tilt.
                    var accel = (_lastResponse.magnitude / _tiltSignCheckWindow)
                                / _lastEffectiveAccelTime;
                    var delivered = DegreesFromAccel(accel);

                    sumProduct += d * delivered;
                    sumSquares += d * d;

                    // A plate cannot deliver more than it was asked for. Anything above this was
                    // the ball already flying, bouncing, or briefly mis-detected - one such rung
                    // is enough to wreck a least-squares fit, so drop it rather than average it in.
                    if (delivered > d * ImplausibleDeliveryFactor)
                    {
                        Debug.LogWarning($"[PlateCheck] {name} at {d:0.0} deg reported " +
                                         $"{delivered:0.00} deg delivered - impossible, so that " +
                                         "reading is discarded. The ball was probably already moving.");
                        continue;
                    }

                    rungGains.Add(accel / d);

                    Debug.Log($"[PlateCheck] {name} commanded {d:0.0} deg -> ball accelerates " +
                              $"{accel:0} mm/s^2 -> plate delivered about {delivered:0.00} deg " +
                              $"({100f * delivered / d:0}% of what was asked for).");
                }

                if (rungGains.Count < 2)
                {
                    Debug.LogWarning($"[PlateCheck] {name} AXIS: only {rungGains.Count} usable " +
                                     "reading(s) - not enough to trust. Re-centre the ball, make " +
                                     "sure it is still, and press P again.");
                    continue;
                }

                // MEDIAN, not a fit. With four rungs and a ball that can be knocked off course by
                // one bad sweep, the median simply ignores the outlier; a least-squares line lets
                // it drag the answer anywhere - which is how this reported gains from 10 to 330
                // mm/s^2/deg across runs of the same machine.
                var plantGain = Median(rungGains);
                var slope = plantGain / BallAccelPerDegree;
                var spread = Spread(rungGains);

                plantGains.Add(plantGain);

                Debug.Log($"[PlateCheck] {name} AXIS: median plant gain {plantGain:0.0} mm/s^2 per " +
                          $"commanded deg = {slope:0.00} deg delivered per commanded deg, from " +
                          $"{rungGains.Count} readings spanning {spread:0}%. " + VerdictFor(slope));
            }

            ApplyGainsFor(plantGains);

            Debug.Log("[PlateCheck] Done. Plate left level.");
            yield return HoldTilt(0, 0f, 0.1f);
        }

        /// <summary>
        /// Sets Constants.k_p / k_d from the plant gain just measured. Scaling both gains by
        /// 102.7/A leaves the open loop L(s) = A*(k_p + k_d*s)/s^2 completely unchanged, so the
        /// +45 deg phase margin the pair was designed for is preserved exactly - only the plant
        /// it is matched to changes. A plate that delivers less tilt simply needs proportionally
        /// more gain; that is a scaling, not a redesign.
        /// </summary>
        private static void ApplyGainsFor(List<float> plantGains)
        {
            if (plantGains.Count == 0)
            {
                Debug.LogWarning("[PlateCheck] No usable plant gain measured, so the PD gains were " +
                                 "left alone.");
                return;
            }

            var a = Median(plantGains);

            // 0.03 was derived against the ideal 102.7 mm/s^2 per degree; see Constants.k_p.
            var gain = Mathf.Clamp(0.03f * (BallAccelPerDegree / a), 0.01f, 0.25f);

            var before = Constants.k_p;
            Constants.k_p = gain;
            Constants.k_d = gain;

            Debug.Log($"[PlateCheck] Measured plant gain {a:0.0} mm/s^2 per commanded deg " +
                      $"({100f * a / BallAccelPerDegree:0}% of an ideal plate). PD gains set to " +
                      $"k_p = k_d = {gain:0.000} (were {before:0.000}) - that restores the designed " +
                      "3.2 rad/s crossover and +45 deg phase margin against YOUR plate.");
        }

        // How far from perpendicular the two tilt axes may be before the machine is rejected.
        private const float MaxTiltAxisSkew = 30f;

        /// <summary>
        /// Every distinct way four arms can be split into two pairs - there are only three, so the
        /// right one can simply be found by trying each. Each entry is a Constants.MotorWiringOrder:
        /// which computed arm rotation is sent to which physical motor.
        ///
        /// Only the PAIRING matters here. Swapping the two members of a pair just flips that tilt's
        /// sign, which the axis-mapping check already sorts out on its own.
        /// </summary>
        private static readonly int[][] CandidatePairings =
        {
            new[] {0, 1, 2, 3},   // arms (0,1) and (2,3) - the original assumption
            new[] {0, 2, 1, 3},   // arms (0,2) and (1,3)
            new[] {0, 2, 3, 1}    // arms (0,3) and (1,2)
        };

        [Header("Motor pairing search (press R)")]
        [SerializeField] private float _pairingSearchDegrees = 3f;

        /// <summary>
        /// Finds which physical motors form each tilt pair, by measurement.
        ///
        /// Translate() assumes arms 0/1 sit on OPPOSITE corners and drive the X tilt, and 2/3 the
        /// Y tilt. If the connectors are ordered around the plate instead, both "pairs" span
        /// adjacent corners and BOTH tilts act on the same physical axis - the plate then cannot
        /// tilt in two independent directions at all, and no amount of tuning or sign-flipping
        /// helps. The signature is the angle between the two tilt axes: it must be 90 degrees.
        ///
        /// So: try each pairing, measure that angle, keep whichever is closest to 90.
        /// </summary>
        private IEnumerator MotorPairingSearchRoutine()
        {
            _isExecuteControlStrategies.Value = false;

            var d = _pairingSearchDegrees;
            var original = Constants.MotorWiringOrder;

            int[] best = null;
            var bestError = float.MaxValue;
            var bestSeparation = 0f;

            Debug.Log($"[Pairing] Trying all {CandidatePairings.Length} ways of pairing the four " +
                      $"arms at +-{d} deg, and keeping whichever the plate can actually execute. " +
                      "Keep the ball near the centre; this takes about a minute.");

            if (!BallIsReadyToMeasure("Pairing"))
            {
                yield break;
            }

            yield return RiseToTestHeight();

            foreach (var candidate in CandidatePairings)
            {
                // Safe to switch while level: at zero tilt all four arm rotations are equal, so a
                // permutation of them is a no-op and nothing jumps.
                yield return HoldTilt(0, 0f, 0.2f);
                Constants.MotorWiringOrder = candidate;

                yield return MeasureAxisResponse(0, d);
                var xResponse = _lastResponse;
                var xOk = _lastResponseValid && _lastResponse.magnitude >= _tiltSignCheckMinDrift;

                yield return MeasureAxisResponse(1, d);
                var yResponse = _lastResponse;
                var yOk = _lastResponseValid && _lastResponse.magnitude >= _tiltSignCheckMinDrift;

                var label = $"{{{candidate[0]},{candidate[1]},{candidate[2]},{candidate[3]}}}";

                if (!xOk || !yOk)
                {
                    Debug.LogWarning($"[Pairing] {label}: the ball barely moved or was lost - no " +
                                     "reading. Re-centre it and press R again if this repeats.");
                    continue;
                }

                var separation = Vector2.Angle(xResponse, yResponse);

                // Score by how much the plate actually MOVED, not by how perpendicular the axes
                // came out. Under a wrong pairing the commanded arm heights are not coplanar, the
                // plate physically cannot take that shape, the arms fight each other and the ball
                // hardly stirs. The pairing that produces real motion is the achievable one - and
                // measuring motion is far more robust than measuring an angle from noisy drifts.
                var strength = xResponse.magnitude + yResponse.magnitude;
                var error = -strength;

                Debug.Log($"[Pairing] {label}: ball moved {strength:0.0}mm total, tilt axes " +
                          $"{separation:0} deg apart.");

                if (error < bestError)
                {
                    bestError = error;
                    bestSeparation = separation;
                    best = candidate;
                }
            }

            yield return HoldTilt(0, 0f, 0.2f);

            if (best == null)
            {
                Constants.MotorWiringOrder = original;

                Debug.LogError("[Pairing] Nothing measured cleanly under any pairing. That usually " +
                               "means the ball was not detected - check the camera image before " +
                               "reading anything into the machine. Wiring order left as it was.");
                yield break;
            }

            Constants.MotorWiringOrder = best;

            Debug.Log($"[Pairing] RESULT -> Constants.MotorWiringOrder = " +
                      $"{{{best[0]},{best[1]},{best[2]},{best[3]}}} - the pairing the plate can " +
                      $"actually execute. Its tilt axes measured {bestSeparation:0} deg apart; " +
                      (bestSeparation >= 90f - MaxTiltAxisSkew && bestSeparation <= 90f + MaxTiltAxisSkew
                          ? "that is perpendicular, as it should be."
                          : "that is NOT the 90 deg it should be, which given the pairing is " +
                            "achievable points at the ball measurement rather than the machine - " +
                            "check detection is solid before trusting it.") +
                      " Now press P, then Space.");

            // The mapping was measured against the OLD pairing, so it is meaningless now.
            _axisMappingCalibrated = false;
        }

        // Rejects a rung whose implied delivery exceeds the command by more than this.
        private const float ImplausibleDeliveryFactor = 1.3f;

        private static float Median(List<float> values)
        {
            var sorted = new List<float>(values);
            sorted.Sort();

            var mid = sorted.Count / 2;

            return sorted.Count % 2 == 1
                ? sorted[mid]
                : 0.5f * (sorted[mid - 1] + sorted[mid]);
        }

        /// <summary>
        /// Max-to-min spread as a percentage of the median - how repeatable the readings were.
        /// Above roughly 60% the machine is not behaving consistently enough to tune against.
        /// </summary>
        private static float Spread(List<float> values)
        {
            var min = float.MaxValue;
            var max = float.MinValue;

            foreach (var v in values)
            {
                min = Mathf.Min(min, v);
                max = Mathf.Max(max, v);
            }

            var median = Median(values);

            return Mathf.Abs(median) > 1e-3f ? 100f * (max - min) / median : 0f;
        }

        private static string VerdictFor(float slope)
        {
            if (slope >= 0.7f)
            {
                return "Healthy - the tilt is getting through.";
            }

            if (slope >= 0.3f)
            {
                return "A lot of the commanded tilt is lost in the linkage - most likely flex, or " +
                       "the four arms fighting each other, since a rigid plate on four arms is " +
                       "over-constrained in tilt. Provided it is a uniform loss and not a deadband " +
                       "the controller is simply tuned around it, which is done automatically.";
            }

            if (slope >= 0.05f)
            {
                return "Very little tilt is reaching the plate. Balancing cannot work like this - " +
                       "the controller only ever asks for about a degree. Fix the mechanics first.";
            }

            return "The plate is not tilting on this axis at all. Check that Machine End Point is " +
                   "Real or ModelAndReal, that the serial port is open, and that both motors of " +
                   "this pair are powered and wired.";
        }

        /// <summary>
        /// One axis, one tilt magnitude. Symmetric bang-bang: +d for T, then -d for 2T, then +d for
        /// T, which returns the ball to where it started with ZERO velocity - the two accelerations
        /// cancel. Reports through _lastResponse / _lastDriftPlus / _lastDriftMinus.
        /// </summary>
        private IEnumerator MeasureAxisResponse(int axis, float d)
        {
            var phase = PhaseFor(d);
            var accelerate = phase - _tiltSignCheckWindow;

            // Seconds of acceleration separating the two samples. The legs are NOT symmetric:
            // the + sample sits early in a short leg, the - sample late in a leg twice as long, so
            //     v_plus  =  a * (accelerate + window/2 - ramp)
            //     v_minus = -a * (phase - window/2)
            // and the divisor is the SUM of those, not twice either one. Using 2x the + leg (the
            // first version here) reported every acceleration about 19% high.
            var tPlus = accelerate + _tiltSignCheckWindow * 0.5f - _tiltRampAllowance;
            var tMinus = phase - _tiltSignCheckWindow * 0.5f;
            _lastEffectiveAccelTime = Mathf.Max(tPlus + tMinus, 0.02f);

            yield return SettleBall();

            yield return TiltAndMeasureDrift(axis, +d, accelerate);
            var driftPlus = _lastDrift;
            var okPlus = _lastDriftValid;

            yield return TiltAndMeasureDrift(axis, -d, 2f * phase - _tiltSignCheckWindow);
            var driftMinus = _lastDrift;
            var okMinus = _lastDriftValid;

            // Third leg cancels the speed the second leg built up. Runs even if the ball was lost,
            // so the plate is never left tilted with a loose ball on it.
            yield return HoldTilt(axis, +d, phase);
            yield return HoldTilt(axis, 0f, 0.1f);

            _lastDriftPlus = driftPlus;
            _lastDriftMinus = driftMinus;
            _lastResponse = driftPlus - driftMinus;
            _lastResponseValid = okPlus && okMinus;
        }

        /// <summary>
        /// The plate never moved the ball, at any tilt up to the clamp. That is not a sign problem,
        /// so say what to check instead of leaving a bare failure in the log.
        /// </summary>
        private void ReportNoTiltResponse()
        {
            Debug.LogError(
                "[TiltSign] The ball did not respond to ANY commanded tilt, up to " +
                $"{_tiltSignCheckLadder[_tiltSignCheckLadder.Length - 1]} deg (Constants.MaxTiltAngle " +
                $"is {Constants.MaxTiltAngle}). The plate is not physically tilting - this is not an " +
                "axis-mapping problem. Check, in this order:\n" +
                "  1. MachineController > Machine End Point must be Real or ModelAndReal. On Model " +
                "the 3D model moves and the hardware never receives anything.\n" +
                "  2. SerialInterface > Port Name must be the Teensy's COM port, and no other " +
                "program may hold it open.\n" +
                "  3. MachineController inspector > Backlash test > 'X +1 deg': the plate joint " +
                "should physically rise 2.609 mm. Measure it with calipers. If it does not move, " +
                "the tilt is not reaching the motors.\n" +
                "  4. If it moves but by much less than 2.6 mm, that is arm backlash - reseat the " +
                "set screws on the D-shafts.");
        }

        /// <summary>
        /// Holds a tilt, then measures how far the ball DRIFTS over a short window - which is a
        /// proxy for its velocity, and that is the quantity that reverses cleanly with the tilt.
        ///
        /// Sampling the ball's POSITION instead does not work, and that was the original mistake
        /// here: tilt one way for t and back the other way for 2t and an ideal ball returns to
        /// almost exactly where it started (the two parabolas cancel), so the position difference
        /// is ~0 mm and whatever it does report is friction and plate level, not the axis mapping.
        /// Velocity under the same sequence goes +v then -v: a large, unambiguous signal.
        /// </summary>
        /// <summary>
        /// Refuses to start a measurement unless the ball is visible, whole, and near the middle.
        /// Cheap to check and it saves a minute of sweeping that would have to be thrown away.
        /// </summary>
        private bool BallIsReadyToMeasure(string routine)
        {
            if (!_hasRawBallPosition)
            {
                Debug.LogWarning($"[{routine}] No ball detected - put it on the plate, check the " +
                                 "image mode is CustomgrayWithInternalImageProcessing, and try again.");
                return false;
            }

            if (!_ballFullyVisible)
            {
                Debug.LogWarning($"[{routine}] The ball is against the edge of the frame, so its " +
                                 "position cannot be trusted. Move it toward the middle and try again.");
                return false;
            }

            var offset = _lastRawBallPosition.magnitude;

            if (offset > _requiredStartRadiusMm)
            {
                Debug.LogWarning($"[{routine}] The ball is {offset:0.0}mm from the centre; this " +
                                 $"needs it within {_requiredStartRadiusMm:0.#}mm before it starts " +
                                 "tilting, or the sweep pushes it straight off. Re-centre and try again.");
                return false;
            }

            return true;
        }

        /// <summary>
        /// Raises the plate to the test height gently, before any of the quick 0.15s moves run.
        /// Nothing else in a sweep changes height, so this is the only move that can throw the ball.
        /// </summary>
        private IEnumerator RiseToTestHeight()
        {
            yield return new WaitUntil(() => _machineController.IsReadyForNextInstruction);

            _machineController.SendSingleInstruction(
                new HLInstruction(_balancingPlateHeight, 0f, 0f, _testHeightMoveTime));

            yield return new WaitForSeconds(_testHeightMoveTime + 0.2f);
        }

        /// <summary>
        /// Levels the plate and waits for the ball to stop rolling, so each axis sweep starts from
        /// rest. Without this the + leg inherits whatever speed the previous sweep left behind and
        /// the two legs come out lopsided - which is what made the first measurements disagree.
        /// </summary>
        private IEnumerator SettleBall()
        {
            yield return HoldTilt(0, 0f, 0.1f);

            var deadline = Time.time + _ballSettleTimeout;

            while (Time.time < deadline)
            {
                var from = _lastRawBallPosition;
                var sawFrom = _hasRawBallPosition;

                yield return new WaitForSeconds(_tiltSignCheckWindow);

                if (sawFrom && _hasRawBallPosition &&
                    (_lastRawBallPosition - from).magnitude < _ballSettleDrift)
                {
                    yield break;
                }
            }

            // Not fatal. The measurement takes the DIFFERENCE between the +d and -d legs, which
            // cancels any constant velocity the ball already had - settling just makes the two legs
            // symmetrical, it is not required for the result to be valid.
            Debug.Log("[Calibration] The ball was still drifting when the sweep started; the +/- " +
                      "difference cancels that, so the measurement still stands.");
        }

        private IEnumerator HoldTilt(int axis, float degrees, float seconds)
        {
            yield return new WaitUntil(() => _machineController.IsReadyForNextInstruction);

            _machineController.SendSingleInstruction(new HLInstruction(
                _balancingPlateHeight,
                axis == 0 ? degrees : 0f,
                axis == 1 ? degrees : 0f,
                0.15f));

            if (seconds > 0f)
            {
                yield return new WaitForSeconds(seconds);
            }
        }

        private IEnumerator TiltAndMeasureDrift(int axis, float degrees, float hold)
        {
            yield return new WaitUntil(() => _machineController.IsReadyForNextInstruction);

            _machineController.SendSingleInstruction(new HLInstruction(
                _balancingPlateHeight,
                axis == 0 ? degrees : 0f,
                axis == 1 ? degrees : 0f,
                0.15f));

            // Let the plate arrive and the ball pick up speed before timing it.
            yield return new WaitForSeconds(hold);

            var from = _lastRawBallPosition;
            var sawFrom = _hasRawBallPosition && _ballFullyVisible;

            yield return new WaitForSeconds(_tiltSignCheckWindow);

            _lastDrift = _lastRawBallPosition - from;
            _lastDriftValid = sawFrom && _hasRawBallPosition && _ballFullyVisible;

            if (!_lastDriftValid && _hasRawBallPosition)
            {
                Debug.LogWarning("[Calibration] The ball reached the edge of the frame, so its " +
                                 "measured centre cannot be trusted - that sample was discarded. " +
                                 "Re-centre the ball, or lower Ball Travel Budget.");
            }
        }

        private void ReportTiltSignCheck(Vector2 xResponse, Vector2 yResponse)
        {
            // The two tilt axes MUST be perpendicular. If they are not, no choice of
            // swap/invert - and no rotation matrix either - can make the loop work, because the
            // machine physically cannot push the ball in two independent directions.
            var separation = Vector2.Angle(xResponse, yResponse);

            if (separation < 90f - MaxTiltAxisSkew || separation > 90f + MaxTiltAxisSkew)
            {
                Debug.LogError(
                    $"[TiltSign] The X and Y tilts move the ball along directions only " +
                    $"{separation:0} deg apart. They MUST be 90 deg apart - the plate cannot be " +
                    "controlled in two directions otherwise, and no software mapping can fix it.\n" +
                    $"  X tilt drives the ball toward {Mathf.Atan2(xResponse.y, xResponse.x) * Mathf.Rad2Deg:0} deg\n" +
                    $"  Y tilt drives the ball toward {Mathf.Atan2(yResponse.y, yResponse.x) * Mathf.Rad2Deg:0} deg\n" +
                    "Near 180 deg means both motor pairs are acting on the SAME physical axis: the " +
                    "four motor connectors are ordered around the plate instead of in opposite " +
                    "pairs. Swap two of them - or set Constants.MotorWiringOrder to {0,2,1,3}, " +
                    "which does the same thing in software - and run this again.");
                return;
            }

            // Which raw camera axis did each tilt actually move the ball along?
            var xUsesCameraY = Mathf.Abs(xResponse.y) > Mathf.Abs(xResponse.x);
            var yUsesCameraX = Mathf.Abs(yResponse.x) > Mathf.Abs(yResponse.y);

            if (xUsesCameraY != yUsesCameraX)
            {
                Debug.LogWarning("[TiltSign] The two axes disagree about whether they are swapped. " +
                                 "The ball probably barely moved - increase Tilt Sign Check Degrees " +
                                 "or Hold. Leaving the previous mapping in place.");
                return;
            }

            var swap = xUsesCameraY;

            // Required: +XTilt moves the ball toward plate +x, +YTilt moves it toward plate -y.
            var xAlong = swap ? xResponse.y : xResponse.x;
            var yAlong = swap ? yResponse.x : yResponse.y;

            var invertX = xAlong < 0f;
            var invertY = yAlong > 0f;

            var unchanged = swap == _swapCameraAxes
                            && invertX == _invertCameraX
                            && invertY == _invertCameraY;

            _swapCameraAxes = swap;
            _invertCameraX = invertX;
            _invertCameraY = invertY;
            _axisMappingCalibrated = true;

            Debug.Log($"[TiltSign] Axis mapping set: swap={swap}, invertX={invertX}, " +
                      $"invertY={invertY}" + (unchanged ? " (unchanged)." : " (CHANGED)."));
        }

        /// <summary>
        /// imgMode 7 is the only mode that produces real ball data - every other mode hands back a
        /// placeholder radius, which now reads as "no ball" and would trip the ball-lost abort
        /// within _ballLostTimeout of arming. Arming in any other mode cannot work, so switch.
        /// </summary>
        private void EnsureDetectionImageMode()
        {
            const Constants.ImgMode detectionMode = Constants.ImgMode.CustomgrayWithInternalImageProcessing;

            if (_cameraPlugin.ImgMode == detectionMode)
            {
                return;
            }

            Debug.LogWarning("Image mode was " + _cameraPlugin.ImgMode + ", which produces no ball " +
                             "data. Switching to " + detectionMode + " so the control strategies " +
                             "have something to run on.");

            _cameraPlugin.ImgMode = detectionMode;
        }

        /// <summary>
        /// Disarms the control strategies and brings the plate back to the working origin after
        /// the ball has been out of sight for longer than _ballLostTimeout. Recover by putting the
        /// ball back on the plate and pressing Space again.
        /// </summary>
        private void AbortOnBallLost()
        {
            Debug.LogWarning("Ball lost for " + _ballLostTimer.ToString("0.00") +
                             "s - disarming control strategies and returning the plate to " +
                             _ballLostRecoveryHeightMm + "mm. Put the ball back on the plate and " +
                             "press Space to re-arm.");

            _isExecuteControlStrategies.Value = false;
            _ballLostTimer = 0f;

            // The !_isExecuteControlStrategies branch above resets the strategies from the next
            // frame on; reset here too so nothing runs on stale state in between.
            foreach (var strategy in _strategies)
            {
                strategy.Reset();
            }

            _currentStrategyIndex = 0;

            _machineStateView.Set("Ball lost", MachineStateView.TiltControlType.None);

            _machineController.SendSingleInstruction(new HLInstruction(
                _ballLostRecoveryHeightMm / 1000f, 0f, 0f, _ballLostRecoveryMoveTime));
        }

        // Ball radius/position calibration log, written to <repo root>/log files/ball_calibration_log.csv
        private static string GetCalibrationLogPath()
        {
            return Path.Combine(Application.dataPath, "..", "..", "..", "..", "log files", "ball_calibration_log.csv");
        }

        private static void LogBallCalibrationSample(string label, BallRadiusAndPosition ball, float distanceMm)
        {
            var path = GetCalibrationLogPath();

            if (!File.Exists(path))
            {
                File.WriteAllText(path, "Timestamp,Label,PixelRadius,PixelX,PixelY,DistanceMm\n");
            }

            var line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss},{label},{ball.Radius},{ball.PositionX},{ball.PositionY},{distanceMm}\n";
            File.AppendAllText(path, line);

            Debug.Log($"Logged '{label}' calibration sample: radius={ball.Radius}px, x={ball.PositionX}px, y={ball.PositionY}px, distance={distanceMm}mm");
        }
    }
}
