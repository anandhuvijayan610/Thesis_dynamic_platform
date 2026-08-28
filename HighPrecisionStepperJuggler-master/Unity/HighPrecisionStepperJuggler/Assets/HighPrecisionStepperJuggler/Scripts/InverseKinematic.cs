using System;
using UnityEngine;
using c = HighPrecisionStepperJuggler.Constants;

namespace HighPrecisionStepperJuggler
{
    public static class InverseKinematics
    {
        /// <summary>
        /// Get joint2 rotation with a given theta1 rotation
        /// </summary>
        /// <param name="theta1">The rotation of joint1</param>
        /// <returns>theta2 (rotation of joint2)</returns>
        public static float CalculateJoint2RotationFromJoint1Rotation(float theta1, float offsetQ)
        {
            var q = c.Q + offsetQ;

            // Clamped to Acos's domain [-1, 1]. Outside it, the requested theta1 has already put
            // joint1 further than joint2's link can reach, which a large enough commanded tilt+
            // height combination CAN do in one shot even though each is individually clamped -
            // MinTiltAngle/MaxTiltAngle/MinPlateHeight/MaxPlateHeight constrain the high-level
            // instruction, not the resulting per-arm reach. Unclamped, Math.Acos of an
            // out-of-range value returns NaN, which this MonoBehaviour would then hand straight
            // to a Transform.localRotation (visible as the "Assertion failed... Input rotation is
            // { NaN, NaN, NaN, NaN }" errors this produced) - and on the real machine, a NaN
            // reaching RealMachine's (int32_t) pulse-count cast is undefined behaviour, sent to an
            // actual stepper. Clamping degrades to the nearest physically reachable angle instead -
            // not the exact unreachable target, but always a safe, defined one.
            var cosArg = Mathf.Clamp((Mathf.Cos(theta1) * c.L1 - q) / c.L2, -1f, 1f);

            return (float)(Mathf.PI - Math.Acos(cosArg));
        }

        /// <summary>
        /// Get joint1 rotation with a given targetHeight
        /// </summary>
        /// <param name="targetY">The given target height (tip of link2)</param>
        /// <returns>theta1 (rotation of joint1)</returns>
        public static float CalculateJoint1RotationFromTargetY(float targetY, float offsetQ)
        {
            // NOTE: ↓ old IK without q-correction.
            //return Mathf.Asin((targetY * targetY + c.L1 * c.L1 - c.L2 * c.L2) / (2f * c.L1 * targetY));

            // y = l_1 sin(x) + sqrt(l_2^2-(-l_1cos(x) + q)^2)
            //     ↓ solve for x (wolfram alpha) ↓
            //
            // x = -cos^(-1)((l_1 (-q) (-4 l_1^2 + 4 l_2^2 - 4 q^2 - 4 y^2)
            //     - 4 sqrt(-l_1^2 q^4 y^2 - 2 l_1^2 q^2 y^4 + 2 l_1^4 q^2 y^2 + 2 l_1^2 l_2^2 q^2 y^2
            //     - l_1^2 y^6 + 2 l_1^4 y^4 + 2 l_1^2 l_2^2 y^4 - l_1^6 y^2 - l_1^2 l_2^4 y^2 + 2 l_1^4 l_2^2 y^2))
            //     /(2 l_1^2 (4 q^2 + 4 y^2)))

            var q = c.Q + offsetQ;
            var a1 = 1f / (2f * c.L1 * c.L1 * (4f * q * q + 4f * targetY * targetY));
            var a2 = -c.L1 * q * (-4f * c.L1 * c.L1 + 4f * c.L2 * c.L2 - 4f * q * q - 4 * targetY * targetY);

            // Clamped to >=0 for the same reason as the Acos clamp below: a targetY past the arm's
            // physical reach makes this polynomial go negative, and Sqrt of a negative number is
            // NaN, not an exception - it would otherwise propagate silently through a2/a3 into the
            // final Acos and from there into a real motor command.
            var a3Inner = Mathf.Max(0f,
                         -c.L1 * c.L1 * q * q * q * q * targetY * targetY
                         - 2f * c.L1 * c.L1 * q * q * targetY * targetY * targetY * targetY
                         + 2f * c.L1 * c.L1 * c.L1 * c.L1 * q * q * targetY * targetY
                         + 2f * c.L1 * c.L1 * c.L2 * c.L2 * q * q * targetY * targetY
                         - c.L1 * c.L1 * targetY * targetY * targetY * targetY * targetY * targetY
                         + 2f * c.L1 * c.L1 * c.L1 * c.L1 * targetY * targetY * targetY * targetY
                         + 2f * c.L1 * c.L1 * c.L2 * c.L2 * targetY * targetY * targetY * targetY
                         - c.L1 * c.L1 * c.L1 * c.L1 * c.L1 * c.L1 * targetY * targetY
                         - c.L1 * c.L1 * c.L2 * c.L2 * c.L2 * c.L2 * targetY * targetY
                         + 2f * c.L1 * c.L1 * c.L1 * c.L1 * c.L2 * c.L2 * targetY * targetY);
            var a3 = -4f * Mathf.Sqrt(a3Inner);

            // Note: The localMaximum of Mathf.Acos(a1 * (a2 - a3)).
            //       e.g. the target_y where Mathf.Acos(a1 * (a2 - a3)) returns exactly 1.0.
            var localMaximum = c.L1 * Mathf.Sin(0f) + Mathf.Sqrt(c.L2*c.L2-Mathf.Pow((-c.L1 * Mathf.Cos(0f) + q), 2f));

            // Clamped to Acos's domain [-1, 1] for a target beyond reach - see the matching clamp
            // in CalculateJoint2RotationFromJoint1Rotation for why this must never reach NaN.
            var acosArg = Mathf.Clamp(a1 * (a2 - a3), -1f, 1f);
            var result = targetY < localMaximum
                ? -Mathf.Acos(acosArg)
                : Mathf.Acos(acosArg);

            return result;
        }
    }
}
