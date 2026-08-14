using System;
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

        private BallData _ballData;
        private int _currentStrategyIndex;
        private bool _isBallPositionLoggingEnabled;

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

        private void GetBallBouncing(Action action = null)
        {
            _strategies.Add(
                BallControlStrategyFactory.Bouncing(5, PIDTiltController.Instance, action: action));
            _strategies.Add(
                BallControlStrategyFactory.BouncingStrong(1, PIDTiltController.Instance));

            for (int i = 0; i < 4; i++)
            {
                _strategies.Add(BallControlStrategyFactory.Bouncing(5, PIDTiltController.Instance));
                _strategies.Add(BallControlStrategyFactory.BouncingStrong(1, PIDTiltController.Instance));
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
                _isExecuteControlStrategies.Value = !_isExecuteControlStrategies.Value;
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

            if (height >= float.MaxValue)
            {
                // couldn't find ball in image
                return;
            }

            var ballPosX = FOVCalculations.PixelPositionToDistanceFromCenter(ballRadiusAndPosition.PositionX, height);
            _gradientDescentX.Hypothesis.SetTheta_0To(ballPosX);
            _gradientDescentX.AddTrainingSet(new TrainingSet(0f, ballPosX));
            _gradientDescentX.UpdateHypothesis();

            var ballPosY = FOVCalculations.PixelPositionToDistanceFromCenter(ballRadiusAndPosition.PositionY, height);
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
