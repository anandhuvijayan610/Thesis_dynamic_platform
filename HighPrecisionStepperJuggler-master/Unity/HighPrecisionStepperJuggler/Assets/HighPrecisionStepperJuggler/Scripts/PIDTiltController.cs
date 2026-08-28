using UnityEngine;

namespace HighPrecisionStepperJuggler.MachineLearning
{
    public class PIDTiltController : ITiltController
    {
        private static readonly PIDTiltController INSTANCE = new PIDTiltController();

        public static PIDTiltController Instance => INSTANCE;

        public CrossVisualizer TargetCrossVisualizer
        {
            set { _targetCrossVisualizer = value; }
        }

        private CrossVisualizer _targetCrossVisualizer;

        public (float xTilt, float yTilt) CalculateTilt(
            Vector2 position,
            Vector2 velocity,
            Vector2 targetPosition,
            float calculatedOnBounceDownwardsVelocity,
            float airborneTime)
        {
            _targetCrossVisualizer.UpdateCrossPosition(targetPosition);

            // The proportional term is driven by the ERROR, not the raw position. This used to
            // ignore targetPosition entirely, which silently pinned the controller to the plate
            // centre no matter what target a strategy asked for. Every existing caller passes
            // Vector2.zero, so this changes nothing in the original demo - it only makes a
            // non-zero balancing target actually work.
            var error = position - targetPosition;

            var p_x = -error.x * Constants.k_p;
            var p_y = -error.y * Constants.k_p;

            var d_x = -velocity.x * Constants.k_d;
            var d_y = -velocity.y * Constants.k_d;

            return (p_x + d_x, -(p_y + d_y));
        }
    }
}
