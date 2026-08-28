using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace HighPrecisionStepperJuggler
{
    public class MachineController : MonoBehaviour
    {
        [SerializeField] private InstructableMachine _realMachine = null;
        [SerializeField] private InstructableMachine _modelMachine = null;

        // How far above the mechanical dead position the working origin sits. Pushed into
        // Constants.OriginHeightOffset in Awake() so it can be tuned from the inspector in mm.
        [SerializeField] private float _originHeightOffsetMm = 20f;

        // Time given to the plate to travel from wherever it is up to the working origin.
        [SerializeField] private float _originMoveTime = 0.5f;

        // Grace period before the very first packet, so the serial link is up before we talk.
        [SerializeField] private float _startupDelay = 0.5f;

        [Header("Backlash test")]
        // Tilt magnitude used by the backlash-test buttons in the inspector.
        [SerializeField] private float _backlashTestTiltDegrees = 1f;

        // Plate height the backlash test runs at. Defaults to the balancing height so the arm
        // geometry - and therefore the pulses-per-degree - matches what the controller sees.
        [SerializeField] private float _backlashTestHeight = 0.05f;

        [SerializeField] private float _backlashTestMoveTime = 0.3f;

        public float BacklashTestTiltDegrees => _backlashTestTiltDegrees;

        private float _elapsedTime;
        private float _totalMoveTime;

        private HLMachineState _levelingOffset = new HLMachineState(0f, 0f, 0f);

        public bool IsReadyForNextInstruction => _elapsedTime > _totalMoveTime;

        // False until the startup move has parked the plate at the working origin. The ball
        // detection pipeline must not feed the control strategies before this flips, because every
        // measured ball height is referenced to the plate-at-origin plane.
        public bool IsAtWorkingOrigin { get; private set; }

        private Coroutine _originRoutine;
        private Coroutine _reversalRoutine;

        private enum MachineEndPoint
        {
            Model,
            Real,
            ModelAndReal
        }

        [SerializeField] private MachineEndPoint _machineEndPoint = MachineEndPoint.Model;

        public void SendSingleInstruction(HLInstruction instruction)
        {
            SendInstructions(new List<HLInstruction>() {instruction});
        }

        private void Awake()
        {
            _elapsedTime = 0f;
            _totalMoveTime = 0f;

            // Inspector value is in mm for legibility; everything downstream works in metres.
            Constants.OriginHeightOffset = _originHeightOffsetMm / 1000f;
        }

        private void Start()
        {
            // Park the plate at the working origin before anything else is allowed to drive it -
            // in particular before ImageProcessingInstructionSender starts feeding ball heights to
            // the controllers, since those heights are measured against the plate-at-origin plane.
            RunMoveToWorkingOrigin(_startupDelay);
        }

        private void RunMoveToWorkingOrigin(float delay)
        {
            if (!Application.isPlaying)
            {
                // Editor buttons outside play mode: no coroutines, just send the move.
                SendSingleInstruction(new HLInstruction(0f, 0f, 0f, _originMoveTime));
                return;
            }

            if (_originRoutine != null)
            {
                StopCoroutine(_originRoutine);
            }

            _originRoutine = StartCoroutine(MoveToWorkingOriginRoutine(delay));
        }

        /// <summary>
        /// Parks the plate at the working origin (Constants.OriginHeightOffset above the mechanical
        /// dead position) and only then declares the machine to be at it.
        /// </summary>
        private IEnumerator MoveToWorkingOriginRoutine(float delay)
        {
            IsAtWorkingOrigin = false;

            if (delay > 0f)
            {
                yield return new WaitForSeconds(delay);
            }

            // SendInstructions silently drops anything sent mid-move, so wait our turn first.
            yield return new WaitUntil(() => IsReadyForNextInstruction);

            // Height 0 == the working origin: SendInstructions adds OriginHeightOffset on top.
            SendSingleInstruction(new HLInstruction(0f, 0f, 0f, _originMoveTime));

            // _totalMoveTime already carries the 50ms microcontroller margin SendInstructions adds.
            yield return new WaitUntil(() => IsReadyForNextInstruction);

            IsAtWorkingOrigin = true;
            _originRoutine = null;

            if (_machineEndPoint == MachineEndPoint.Model)
            {
                Debug.LogWarning("[MachineController] Machine End Point is Model - the 3D model " +
                                 "moves but NOTHING is sent to the hardware. Set it to Real or " +
                                 "ModelAndReal to drive the actual machine.");
            }
            else
            {
                Debug.Log($"[MachineController] Machine End Point: {_machineEndPoint}.");
            }

            Debug.Log("[MachineController] Plate parked at working origin: " +
                      (Constants.OriginHeightOffset * 1000f) +
                      "mm above the mechanical dead position. " +
                      "All high-level heights are now measured from here.");
        }

        private void Update()
        {
            _elapsedTime += Time.deltaTime;

            if (Input.GetKeyDown(KeyCode.UpArrow))
            {
                SendSingleInstruction(new HLInstruction(0.01f, 0f, 0.05f, 0.2f, true));
            }

            if (Input.GetKeyDown(KeyCode.DownArrow))
            {
                SendSingleInstruction(new HLInstruction(0.01f, 0f, -0.05f, 0.2f, true));
            }

            if (Input.GetKeyDown(KeyCode.LeftArrow))
            {
                SendSingleInstruction(new HLInstruction(0.01f, 0.05f, 0f, 0.2f, true));
            }

            if (Input.GetKeyDown(KeyCode.RightArrow))
            {
                SendSingleInstruction(new HLInstruction(0.01f, -0.05f, 0f, 0.2f, true));
            }

            if (Input.GetKeyDown(KeyCode.O))
            {
                GoToOrigin();
            }

            if (Input.GetKeyDown(KeyCode.H))
            {
                GoToMechanicalZero();
            }

            if (Input.GetKeyDown(KeyCode.Alpha1))
            {
                SendSingleInstruction(new HLInstruction(0.01f, 0f, 0f, 0.25f));
            }

            if (Input.GetKeyDown(KeyCode.Alpha2))
            {
                SendSingleInstruction(new HLInstruction(0.02f, 0f, 0f, 0.25f));
            }

            if (Input.GetKeyDown(KeyCode.Alpha3))
            {
                SendSingleInstruction(new HLInstruction(0.03f, 0f, 0f, 0.25f));
            }

            if (Input.GetKeyDown(KeyCode.Alpha4))
            {
                SendSingleInstruction(new HLInstruction(0.04f, 0f, 0f, 0.25f));
            }

            if (Input.GetKeyDown(KeyCode.Alpha5))
            {
                SendSingleInstruction(new HLInstruction(0.05f, 0f, 0f, 0.25f));
            }

            if (Input.GetKeyDown(KeyCode.Alpha6))
            {
                SendSingleInstruction(new HLInstruction(0.06f, 0f, 0f, 0.25f));
            }

            if (Input.GetKeyDown(KeyCode.Alpha7))
            {
                SendSingleInstruction(new HLInstruction(0.07f, 0f, 0f, 0.25f));
            }

            if (Input.GetKeyDown(KeyCode.Alpha8))
            {
                SendSingleInstruction(new HLInstruction(0.08f, 0f, 0f, 0.25f));
            }

            if (Input.GetKeyDown(KeyCode.Alpha9))
            {
                SendSingleInstruction(new HLInstruction(0.09f, 0f, 0f, 0.25f));
            }

            if (Input.GetKeyDown(KeyCode.Alpha0))
            {
                SendSingleInstruction(new HLInstruction(0.002f, 0f, 0f, 0.25f));
                
                /*
                var moveTime = 0.3f;
                var tilt = 0.06694f;
                SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.09f, 0.0f, 0.0f, 0.5f),
                    new HLInstruction(0.01f, 0.0f, 0.0f, 0.5f),
                    new HLInstruction(0.02f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.03f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.04f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.05f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.06f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.07f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.09f, 0f, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, -tilt, 0.0f, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.08f, -tilt, 0.0f, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.01f, tilt, 0.0f, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.08f, tilt, 0.0f, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.01f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0f, -tilt, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.08f, 0f, -tilt, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0f, tilt, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.08f, 0f, tilt, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0f, -tilt, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, 0f, -tilt, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0f, tilt, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, 0f, tilt, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0.0f, 0.0f, 0.5f),
                    new HLInstruction(0.05f, 0.0f, 0.0f, 0.5f),
                });
                */
            }
        }

        public void SendInstructions(List<HLInstruction> instructions)
        {
            if (_elapsedTime < _totalMoveTime)
            {
                return;
            }
            
            // add tilt as HighLevelInstruction in here
            var levelingInstructions = instructions.Where(instruction => instruction.IsLevelingInstruction);

            foreach (var instruction in levelingInstructions)
            {
                var levelingOnlyState = instruction.TargetHLMachineState -
                                        new HLInstruction(0.01f, 0f, 0f, 0.2f).TargetHLMachineState;
                
                _levelingOffset += levelingOnlyState;
            }

            // Every instruction is lifted by the working-origin offset, so a high-level height of
            // 0 lands OriginHeightOffset above the mechanical dead position rather than on it.
            // This is deliberately NOT folded into Constants.OriginMachineState: that state is the
            // firmware's zero, and InstructableMachine.Instruct() subtracts it from every target -
            // putting the offset in both places would cancel it out and the plate would never move.
            var originOffset = new HLMachineState(Constants.OriginHeightOffset, 0f, 0f);

            var llInstructions = instructions.Select(instruction =>
            {
                // MoveTime 0 on the added instruction: operator+ sums MoveTime as well.
                var i = instruction +
                        new HLInstruction(_levelingOffset + originOffset, 0f, instruction.IsLevelingInstruction);
                return i.Translate();
            }).ToList();

            _totalMoveTime = 0f;
            _elapsedTime = 0f;
            foreach (var instruction in instructions)
            {
                _totalMoveTime += instruction.MoveTime;
            }
            //NOTE: we're adding 50ms to make sure that the microcontroller is done before new data gets sent.
            _totalMoveTime += 0.050f;
            
            switch (_machineEndPoint)
            {
                case MachineEndPoint.Model:
                    _modelMachine.Instruct(llInstructions);
                    break;

                case MachineEndPoint.Real:
                    _realMachine.Instruct(llInstructions);
                    break;

                case MachineEndPoint.ModelAndReal:
                    _modelMachine.Instruct(llInstructions);
                    _realMachine.Instruct(llInstructions);
                    break;
            }
        }

        /// <summary>
        /// Sends one tilt at the backlash-test height and logs how far the plate joint should
        /// physically move, so it can be checked against a caliper or dial indicator. Backlash
        /// shows up as the plate not moving at all until the commanded tilt exceeds the play.
        /// </summary>
        public void SendTiltTest(float xTilt, float yTilt)
        {
            SendSingleInstruction(
                new HLInstruction(_backlashTestHeight, xTilt, yTilt, _backlashTestMoveTime));

            var tilt = Mathf.Max(Mathf.Abs(xTilt), Mathf.Abs(yTilt));
            var rise = Mathf.Sin(tilt * Mathf.Deg2Rad) * Constants.PlateWidth / 2f * 1000f;

            Debug.Log($"[Backlash] tilt X={xTilt:0.###} Y={yTilt:0.###} deg -> the plate joint " +
                      $"should sit {rise:0.000} mm off level. Measure it.");
        }

        /// <summary>
        /// Drives the X tilt +d -> 0 -> -d -> 0 repeatedly. Every step is a direction reversal for
        /// the motor pair, which is the only condition under which backlash shows itself - a
        /// monotonic move like the height calibration never reveals it.
        /// </summary>
        public void RunTiltReversalCycle(int cycles = 5)
        {
            if (!Application.isPlaying)
            {
                Debug.LogWarning("[Backlash] The reversal cycle has to wait between moves, so it " +
                                 "only runs in play mode. Use the single-tilt buttons instead.");
                return;
            }

            if (_reversalRoutine != null)
            {
                StopCoroutine(_reversalRoutine);
            }

            _reversalRoutine = StartCoroutine(TiltReversalCycleRoutine(cycles));
        }

        private IEnumerator TiltReversalCycleRoutine(int cycles)
        {
            var d = _backlashTestTiltDegrees;
            var rise = Mathf.Sin(d * Mathf.Deg2Rad) * Constants.PlateWidth / 2f * 1000f;

            Debug.Log($"[Backlash] Reversal cycle: +{d} -> 0 -> -{d} -> 0 deg, x{cycles}. Each " +
                      $"end stop should sit {rise:0.000} mm off level. Watch for the plate lagging " +
                      "a direction change, or sitting still and then lurching once the slack takes up.");

            var steps = new[] {d, 0f, -d, 0f};

            for (int i = 0; i < cycles; i++)
            {
                foreach (var tilt in steps)
                {
                    yield return new WaitUntil(() => IsReadyForNextInstruction);

                    SendSingleInstruction(
                        new HLInstruction(_backlashTestHeight, tilt, 0f, _backlashTestMoveTime));
                }
            }

            yield return new WaitUntil(() => IsReadyForNextInstruction);

            Debug.Log("[Backlash] Reversal cycle done.");
            _reversalRoutine = null;
        }

        /// <summary>
        /// Goes to the WORKING origin - Constants.OriginHeightOffset above the mechanical dead
        /// position. Because it travels as a normal instruction it also keeps whatever manual
        /// leveling has been dialled in with the arrow keys, which GoToMechanicalZero() discards.
        /// </summary>
        public void GoToOrigin()
        {
            RunMoveToWorkingOrigin(0f);
        }

        /// <summary>
        /// Drives all four motors back to rotation 0 - the machine's mechanical home, with the
        /// plate on its dead rest position and no leveling applied. This is below the working
        /// origin, so the machine is no longer at it afterwards.
        /// </summary>
        public void GoToMechanicalZero()
        {
            if (_originRoutine != null)
            {
                StopCoroutine(_originRoutine);
                _originRoutine = null;
            }

            // The plate is no longer at the working origin, so ball heights are no longer
            // referenced correctly - press O (or "Go to origin") to come back and re-arm detection.
            IsAtWorkingOrigin = false;

            switch (_machineEndPoint)
            {
                case MachineEndPoint.Model:
                    _modelMachine.GoToOrigin();
                    break;

                case MachineEndPoint.Real:
                    _realMachine.GoToOrigin();
                    break;

                case MachineEndPoint.ModelAndReal:
                    _modelMachine.GoToOrigin();
                    _realMachine.GoToOrigin();
                    break;
            }
        }
    }
}
