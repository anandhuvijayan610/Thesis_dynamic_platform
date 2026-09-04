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

        // Integral state, and the last command actually issued so the next one can be rate
        // limited relative to it rather than jumping straight to whatever the PD asks for.
        private float _integralX;
        private float _integralY;
        private float _outX;
        private float _outY;
        private float _lastTiltTime = -1f;

        /// <summary>
        /// Drops the integral and the rate-limiter history.
        ///
        /// Must be called whenever the ball is lost or a run ends, or the accumulated term is
        /// still leaning the plate when the next ball arrives.
        /// </summary>
        public void Reset()
        {
            _integralX = 0f;
            _integralY = 0f;
            _outX = 0f;
            _outY = 0f;
            _lastTiltTime = -1f;
        }

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

            var now = Time.time;
            var dt = _lastTiltTime < 0f ? 0f : Mathf.Clamp(now - _lastTiltTime, 0f, 0.5f);
            _lastTiltTime = now;

            var p_x = -error.x * Constants.k_p;
            var p_y = -error.y * Constants.k_p;

            var d_x = -velocity.x * Constants.k_d;
            var d_y = -velocity.y * Constants.k_d;

            // Integral, clamped on its own CONTRIBUTION in degrees rather than on the raw sum, so
            // the bound means something physical and does not change meaning when k_i is retuned.
            // What it is for is the residual slope the linkage carries at any given height: a PD
            // loop can only ever fight that to a standing offset, which is a ball that settles
            // reliably off centre.
            _integralX = Mathf.Clamp(_integralX - error.x * Constants.k_i * dt,
                -Constants.IntegralClampDegrees, Constants.IntegralClampDegrees);
            _integralY = Mathf.Clamp(_integralY - error.y * Constants.k_i * dt,
                -Constants.IntegralClampDegrees, Constants.IntegralClampDegrees);

            var xTilt = Mathf.Clamp(p_x + d_x + _integralX,
                Constants.MinTiltAngle, Constants.MaxTiltAngle);
            var yTilt = Mathf.Clamp(p_y + d_y + _integralY,
                Constants.MinTiltAngle, Constants.MaxTiltAngle);

            // Rate limit. The clamp above bounds how FAR the plate may tilt; this bounds how fast
            // the command may get there, which is the part the ball feels. A tilt that jumps
            // several degrees inside one move swings the plate corner through millimetres in a
            // tenth of a second, and the vertical acceleration that implies is what flicks the
            // ball off the surface - the plate is then throwing it rather than steering it.
            var maxStep = Constants.MaxTiltRateDegreesPerSecond * dt;
            if (dt > 0f && maxStep > 0f)
            {
                xTilt = _outX + Mathf.Clamp(xTilt - _outX, -maxStep, maxStep);
                yTilt = _outY + Mathf.Clamp(yTilt - _outY, -maxStep, maxStep);
            }

            _outX = xTilt;
            _outY = yTilt;

            // Y is negated on the way out, as it always has been on this rig: the camera's y axis
            // and the plate's y tilt run opposite ways. Left alone deliberately - the sign
            // convention here was validated on the machine and is not what the port is changing.
            return (xTilt, -yTilt);
        }
    }
}
