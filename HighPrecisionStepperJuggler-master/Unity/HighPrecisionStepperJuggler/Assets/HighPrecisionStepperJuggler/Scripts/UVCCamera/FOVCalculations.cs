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
        /// above that, which moves it exactly that much FURTHER from the camera - hence the
        /// addition. Keep BallHeightAtOrigin defined at the dead position and let this property do
        /// the shifting, so changing the offset does not invalidate the calibration.
        ///
        /// SIGN FIXED 2026-08-28 - this subtracted the offset until then, which is backwards. The
        /// 2026-08-26 calibration sweep settles the direction beyond doubt: commanding 0 / 20 / 50mm
        /// above the working origin measured 169.05 / 133.56 / 100.13 px, i.e. camera distances of
        /// 69.95 / 89.42 / 120.14 mm. Raising the plate 50mm moved it 50.2mm FURTHER away, so a
        /// higher plate is a SMALLER radius and the offset has to add.
        ///
        /// The error was invisible while OriginHeightOffset was 2mm (BallHeightAtOrigin had been
        /// fitted around the wrong sign, so the two cancelled at exactly that offset) and only
        /// appeared when the offset was raised: at 20mm it put the reference plane at 51.95mm
        /// instead of 87.95mm, reporting a ball resting on the plate as **+36mm above the origin**.
        /// </summary>
        public static float CameraToPlateDistanceAtOrigin =>
            c.BallHeightAtOrigin + c.OriginHeightOffset * 1000f;

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

        // Radius in pixels a ball resting at the given height above the WORKING origin should
        // appear with - the exact inverse of RadiusToDistance above, sharing its constants so the
        // two can never drift apart.
        public static float DistanceToRadius(float heightAboveOriginInMm)
        {
            var distanceFromCamera = heightAboveOriginInMm + CameraToPlateDistanceAtOrigin;

            if (distanceFromCamera <= 0f)
            {
                return float.MaxValue;
            }

            var phiInDegrees = Mathf.Atan(c.RadiusOfPingPongBall / distanceFromCamera) * Mathf.Rad2Deg;
            return phiInDegrees / c.CameraFOVInDegrees * c.CameraResolutionWidth;
        }

        // The commanded plate height in [mm] above the working origin, and the one before it.
        // MachineController.SendInstructions publishes these on every move; nothing else should
        // write them. Kept as the pair rather than just the latest because a move takes time: while
        // the plate is travelling from one to the other it is physically somewhere BETWEEN the two,
        // so only the lower of the pair bounds how close to the camera the ball can currently be.
        private static float _commandedPlateHeightInMm;
        private static float _previousCommandedPlateHeightInMm;

        public static void ReportCommandedPlateHeight(float heightAboveOriginInMm)
        {
            _previousCommandedPlateHeightInMm = _commandedPlateHeightInMm;
            _commandedPlateHeightInMm = heightAboveOriginInMm;
        }

        // Tolerance on the cap below. Covers detector noise (measured +-0.23px on a stable ball),
        // the plate under- or overshooting its commanded height, and the fact that the ball sits on
        // TOP of the plate rather than at the plate plane.
        //
        // 1.25, not the 1.10 it was. Those three allowances are all about the ball's true position;
        // none of them covers the fact that the BORDER TRACER AND THE MODEL MEASURE DIFFERENTLY.
        // DistanceToRadius inverts a lens formula fitted to one particular way of measuring a
        // radius; imgMode 7 measures its own way, by tracing the boundary of everything above
        // Constants.Threshold, and on this rig it reads consistently larger. Measured at the 20mm
        // working origin: a clean, complete ball (roundness 0.90, which is a perfect digital
        // circle) traced at r=157..159px against a predicted 136 - about 17% over, frame after
        // frame, with the old cap at 149 rejecting every one of them. The machine sat idle while
        // the detector was working perfectly.
        //
        // That is a calibration difference between two measurement methods, not an implausible
        // ball, and this cap exists to reject the latter. It still does: the ceiling shows up at
        // r=377, nearly three times the prediction, and is thrown out with room to spare.
        //
        // Worth knowing what this does NOT fix. If the plate is genuinely not reaching its
        // commanded height - the firmware's zero is its power-on position and drifts with lost
        // steps - the radius is honestly reporting that, and widening the cap only hides it. The
        // tell is the reported ball HEIGHT being wrong rather than the detection failing, since
        // every juggling stage keys off that height. Power-cycle with the plate at rest and
        // re-check before assuming this is the whole answer.
        private const float BallRadiusToleranceFactor = 1.25f;

        /// <summary>
        /// Largest radius in pixels the ball could plausibly have right now, given where the plate
        /// has been commanded to.
        ///
        /// This works because the constraint is one-sided and physical: the ball rests on the plate
        /// or is in the air ABOVE it, and it can never be BELOW it. Height maps monotonically to
        /// radius (higher plate = further from the down-facing camera = smaller radius), so the
        /// plate's own height puts a hard ceiling on how large the ball can legitimately look. A
        /// blob bigger than that is not the ball, whatever else it might be.
        ///
        /// Deliberately only an upper bound - no matching lower bound. During the juggling stages
        /// the ball is supposed to leave the plate, and how high it goes is exactly the thing not
        /// known in advance, so any lower bound would be guesswork that could reject a real ball at
        /// the top of its flight. Small blobs are already handled by HT21Parameters.MinRadius.
        /// </summary>
        public static float MaxPlausibleBallRadiusInPixels
        {
            get
            {
                var lowestPlateHeight = Mathf.Min(_commandedPlateHeightInMm, _previousCommandedPlateHeightInMm);
                return DistanceToRadius(lowestPlateHeight) * BallRadiusToleranceFactor;
            }
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
