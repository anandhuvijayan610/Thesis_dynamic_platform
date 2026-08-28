using UnityEngine;
using c = HighPrecisionStepperJuggler.Constants;

namespace HighPrecisionStepperJuggler
{
    public static class FOVCalculations
    {
        // Anything smaller than this is not a ball. UVCCameraPlugin.UpdateImageProcessing() hands
        // back a placeholder radius of 0.1px when no ball was found, and the pinhole model turns
        // that into a perfectly finite ~94 metre "height" - which sails straight past the
        // "height >= float.MaxValue" no-ball guard in ImageProcessingInstructionSender and feeds
        // the gradient descents garbage. Reject it here instead, where the model is.
        private const float MinPlausibleRadiusInPixels = 1f;

        /// <summary>
        /// Camera-to-ball-centre distance in [mm] with the ball resting on the plate at the
        /// WORKING origin, i.e. the plane every reported height is measured from.
        ///
        /// Constants.BallHeightAtOrigin is calibrated against the MECHANICAL dead position (all
        /// four motors at rotation 0). MachineController parks the plate Constants.OriginHeightOffset
        /// above that, which moves it exactly that much CLOSER to the down-facing camera - hence
        /// the subtraction. Keep BallHeightAtOrigin defined at the dead position and let this
        /// property do the shifting, so changing the offset does not invalidate the calibration.
        /// </summary>
        public static float CameraToPlateDistanceAtOrigin =>
            c.BallHeightAtOrigin - c.OriginHeightOffset * 1000f;

        // Returns height above the plate at the WORKING origin, in [mm]. Zero means the ball is
        // resting on the plate while the plate sits at the working origin; float.MaxValue means
        // "no ball", which is what callers test for.
        public static float RadiusToDistance(float radius)
        {
            if (radius < MinPlausibleRadiusInPixels)
            {
                return float.MaxValue;
            }

            var distanceFromCamera = c.RadiusOfPingPongBall /
                                     Mathf.Tan((radius / c.CameraResolutionWidth) * c.CameraFOVInDegrees *
                                               Mathf.Deg2Rad);

            return distanceFromCamera - CameraToPlateDistanceAtOrigin;
        }

        // Returns distance from center of plate in either X or Y direction (depending whether the provided)
        // pixelPosition is in the X or Y direction[mm]
        public static float PixelPositionToDistanceFromCenter(float pixelPosition, float distanceFromPlate)
        {
            // NOTE: distance is zero at center of plate. Inverse of RadiusToDistance above, so it
            //       has to walk back through the same working-origin reference plane.
            var distanceFromCamera = distanceFromPlate + CameraToPlateDistanceAtOrigin;
            var phi = c.CameraFOVInDegrees / 2f * pixelPosition / (c.CameraResolutionWidth / 2f);
            return Mathf.Tan(phi * Mathf.Deg2Rad) * distanceFromCamera;
        }
    }
}
