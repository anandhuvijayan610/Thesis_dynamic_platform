using System;

namespace HighPrecisionStepperJuggler
{
    public sealed class BallControlStrategy : IBallControlStrategy
    {
        private readonly Func<BallData, MachineController, int, bool> _executeFunc;
        private readonly int _duration;
        private readonly bool _usesBallPositionPrediction;
        private readonly Action _onStrategyExecutionStart;
        
        private int _instructionsSentCount;
        
        public bool UsesBallPositionPrediction => _usesBallPositionPrediction;

        public Action OnStrategyExecutionStart => _onStrategyExecutionStart;

        public BallControlStrategy(Func<BallData, MachineController, int, bool> executeFunc,
            int duration, bool usesBallPositionPrediction = false, Action onStrategyExecutionStart = null)
        {
            _duration = duration;
            _executeFunc = executeFunc;
            _usesBallPositionPrediction = usesBallPositionPrediction;
            _onStrategyExecutionStart = onStrategyExecutionStart;
        }

        public bool Execute(BallData ballData, MachineController machineController)
        {
            var instructionsSent = _executeFunc(ballData, machineController, _instructionsSentCount);
            if (instructionsSent)
            {
                _instructionsSentCount++;
            }

            return _instructionsSentCount >= _duration;
        }

        public void Reset()
        {
            _instructionsSentCount = 0;
        }
    }

    /// <summary>
    /// Balances at a fixed height and finishes when the ball has actually SETTLED, rather than
    /// after a fixed number of instructions the way BallControlStrategy does.
    ///
    /// Needed because "hold it until the ball is centred and staying there" is a condition on the
    /// ball, not a duration: how long a ball takes to come to rest depends on where it was and how
    /// fast it was moving when the stage started, and after a juggling stage it is still bouncing.
    /// A fixed cycle count either cuts the settle short or wastes time waiting after it is done.
    ///
    /// "Settled" deliberately requires all three of near-target, slow, and down on the plate, held
    /// for several consecutive cycles. Position alone is not enough - a ball rolling briskly
    /// through the middle satisfies it for one frame - and neither is position plus speed, because
    /// a ball at the apex of a bounce is directly over the target and momentarily near zero
    /// vertical speed too.
    /// </summary>
    public sealed class BalancingUntilSettledStrategy : IBallControlStrategy
    {
        private readonly Func<BallData, MachineController, bool> _executeFunc;
        private readonly Func<BallData, bool> _isSettled;
        private readonly int _holdCycles;
        private readonly int _maxCycles;
        private readonly Action _onStrategyExecutionStart;

        private int _instructionsSentCount;
        private int _settledStreak;

        public bool UsesBallPositionPrediction => false;

        public Action OnStrategyExecutionStart => _onStrategyExecutionStart;

        public BalancingUntilSettledStrategy(
            Func<BallData, MachineController, bool> executeFunc,
            Func<BallData, bool> isSettled,
            int holdCycles,
            int maxCycles,
            Action onStrategyExecutionStart = null)
        {
            _executeFunc = executeFunc;
            _isSettled = isSettled;
            _holdCycles = holdCycles;
            _maxCycles = maxCycles;
            _onStrategyExecutionStart = onStrategyExecutionStart;
        }

        public bool Execute(BallData ballData, MachineController machineController)
        {
            var instructionsSent = _executeFunc(ballData, machineController);
            if (instructionsSent)
            {
                _instructionsSentCount++;
                _settledStreak = _isSettled(ballData) ? _settledStreak + 1 : 0;
            }

            // The cycle cap is a backstop, not the normal exit: a ball that never quite settles
            // (a slight plate tilt it cannot overcome, say) would otherwise hold the program here
            // forever, and the stages after this one would never run.
            return _settledStreak >= _holdCycles || _instructionsSentCount >= _maxCycles;
        }

        public void Reset()
        {
            _instructionsSentCount = 0;
            _settledStreak = 0;
        }
    }

    public interface IBallControlStrategy
    {
        bool Execute(BallData ballData, MachineController machineController);
        bool UsesBallPositionPrediction { get; }
        Action OnStrategyExecutionStart { get; }
        void Reset();
    }
}
