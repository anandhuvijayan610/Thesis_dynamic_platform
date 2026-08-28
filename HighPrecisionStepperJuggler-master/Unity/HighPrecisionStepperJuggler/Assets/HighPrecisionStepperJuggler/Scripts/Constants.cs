using System;
using System.Collections.Generic;

namespace HighPrecisionStepperJuggler
{
    public static class Constants
    {
        // Width of plate (in localSpace) from joint to joint
        public const float PlateWidth = 0.299f;

        // Offset from motor axis to upper Joint
        // public static readonly float Q = 0.069023f;
        public const float Q = 0.070023f;

        // Length of Links
        public const float L1 = 0.089f;
        public const float L2 = 0.080f;

        // Camera-to-ball-centre distance in [mm] with the ball resting on the plate at the
        // MECHANICAL dead position (all four motors at rotation 0). Reported heights are measured
        // from the WORKING origin instead - FOVCalculations.CameraToPlateDistanceAtOrigin shifts
        // this by OriginHeightOffset, so calibrate this one at the dead position and leave the
        // offset to do its own work.
        public static float BallHeightAtOrigin = 71.95f;

        // Which physical motor each computed arm rotation is sent to.
        //
        // ExtensionMethods.Translate() puts arms 0 and 1 on the X tilt pair and arms 2 and 3 on
        // the Y pair, and it assumes each pair sits on OPPOSITE corners of the plate. If the motor
        // connectors are ordered around the square instead, both "pairs" end up spanning adjacent
        // corners - and then BOTH tilt commands act on the same physical axis, 180 degrees apart,
        // so the plate physically cannot tilt in two independent directions. Measured on this rig
        // 2026-08-26: the X and Y tilt responses were 130-172 deg apart across six runs, where
        // perpendicular pairs must give 90.
        //
        // {0,1,2,3} is the identity. {0,2,1,3} swaps physical motors 2 and 3, which converts
        // "adjacent corner" pairing into "opposite corner" pairing without rewiring anything.
        // MEASURED CORRECT 2026-08-26: leave this as the identity.
        //
        // A rigid plate on four arms is over-constrained - it has three degrees of freedom (height
        // and two tilts) driven by four actuators - so the four arm heights are not free. They must
        // satisfy h_a + h_b = h_c + h_d, where (a,b) and (c,d) are the pairs on OPPOSITE corners.
        // Translate() always satisfies that for pairs (0,1) and (2,3).
        //
        // That makes the pairing directly testable: command a pure X tilt under each candidate
        // order and only the one matching the real geometry is achievable - under a wrong order the
        // command asks for a non-planar set of heights, the arms fight each other and the plate
        // barely moves. On this machine the identity order is the one that moves it, so physical
        // motors 0/1 really are on opposite corners, and 2/3 on the other pair. Press R to re-test.
        public static int[] MotorWiringOrder = {0, 1, 2, 3};

        public const float HeightOrigin = 0.0566f;

        // WORKING ORIGIN OFFSET, in metres, above the mechanical dead position.
        //
        // "Mechanical dead position" = all four motors at rotation 0, which is what
        // InstructableMachine.GoToOrigin() commands and what the firmware treats as its zero.
        // The plate resting there has no downward travel left, so the working origin is parked
        // this far above it and THAT is what every high-level height is measured from:
        //     physical plate height = HeightOrigin + OriginHeightOffset + HLMachineState.Height
        // MachineController applies the offset to every instruction it sends and parks the plate
        // here on Start(), before the ball-detection pipeline is allowed to feed the controllers.
        //
        // Overridden at runtime from MachineController's "_originHeightOffsetMm" inspector field;
        // this value is the fallback.
        //
        // Raising the plate moves it this much CLOSER to the down-facing camera, so the ball
        // height model has to shift its reference plane by the same amount:
        // FOVCalculations.CameraToPlateDistanceAtOrigin does exactly that. BallHeightAtOrigin
        // stays calibrated at the mechanical dead position - do not hand-subtract the offset from
        // it as well, or it gets counted twice.
        public static float OriginHeightOffset = 0.020f;
        public const int BaudRate = 921600;

        // Re-calibrated 2026-08-26 after the camera mount moved. Least-squares fit of
        // d = RadiusOfPingPongBall / tan(radius_px * FOV / CameraResolutionWidth) over three
        // commanded plate heights (0 / 20 / 50 mm above the working origin), 5 samples each:
        //   radius 169.05 / 133.56 / 100.13 px  ->  FOV 60.41 deg, residuals -0.52 / +0.20 mm.
        // The tan() form beat a sin() sphere model on this data (rms 0.32 vs 0.40 mm), so the
        // formula in FOVCalculations is left alone. Previous value 77.9 belonged to an older,
        // further-back camera position and is invalid for the current mount.
        public static float CameraFOVInDegrees = 60.41f;
        public static float RadiusOfPingPongBall = 20.0f;

        // What we ASK the driver for. Note this camera does not deliver it - see FrameWidth.
        public static int CameraResolutionWidth = 640;
        public static int CameraResolutionHeight = 480;

        // What the driver ACTUALLY delivers: this camera's native mode is portrait 480x640, so a
        // 640x480 request comes back transposed. Set from the driver readback in
        // UVCCameraPlugin.Start(); the defaults here are only a fallback.
        // Every routine that indexes into the Color32[] pixel buffer must use THESE, not the
        // requested values above - indexing a 480-wide image with a 640 stride makes each row
        // advance skip a row and a bit, which silently corrupted imgMode 7's detection.
        // FOVCalculations deliberately still uses CameraResolutionWidth: the FOV constant was
        // calibrated against that formula, so changing it would invalidate the calibration.
        public static int FrameWidth = 480;
        public static int FrameHeight = 640;

        public static readonly LLMachineState OriginMachineState = new HLMachineState(0f, 0f, 0f).Translate();
        public static readonly LLMachineState ZeroMachineState = new LLMachineState(0f, 0f, 0f, 0f, 0f, 0f, 0f, 0f);

        public static float MaxTiltAngle = 5f;
        public static float MinTiltAngle = -5f;
        public static float MaxPlateHeight = 90f;
        public static float MinPlateHeight = 0f;

        // PD Controller, re-derived 2026-08-26.
        //
        // A ball on a tilting plate is a double integrator: xdd = c*g*sin(tilt). A ping-pong ball
        // is a thin spherical shell, so c = 3/5 and the plant gain is 102.7 mm/s^2 per degree.
        // With the loop closed at ~0.15s (0.1s move + the 50ms microcontroller margin), the old
        // k_p=0.05 / k_d=0.005 crossed over at 2.30 rad/s with a phase margin of **-6.8 deg**,
        // i.e. unstable on paper - the ball could only ever oscillate its way off the plate, no
        // matter how the tilt signs were wired.
        //
        // k_p=0.03 / k_d=0.03 crosses at 3.23 rad/s with +45 deg of phase margin (+36 deg if the
        // real delay is closer to 0.2s). The derivative term now does most of the work, which is
        // what a delayed double integrator needs: the plate reacts to the ball's VELOCITY - it
        // lifts the side the ball is rolling toward - rather than waiting for the error to build.
        //
        // Raising k_p makes it faster but eats margin fast: k_p=0.10/k_d=0.05 is only +7 deg at
        // 0.2s delay. If you want a snappier response, first shorten the loop delay
        // (ImageProcessingInstructionSender._balancingMoveTime), then re-derive these.
        // 0.07, not 0.03: 0.03 was derived against an IDEAL plate of 102.7 mm/s^2 per commanded
        // degree. This plate was measured at 46.1 (a clean PlateCheck run), i.e. it delivers about
        // 45% of the tilt it is asked for, so the loop gain has to be scaled by 102.7/46.1 = 2.2
        // to get back to the crossover and phase margin the pair was designed for. At 0.03 the
        // controller corrects small drifts fine but cannot arrest a ball that is already moving -
        // which is exactly the reported behaviour. Press P to re-measure and re-tune automatically.
        public static float k_p = 0.05f;
        public static float k_d = 0.07f;

        public static float BallVisualizationFadeOutTime = 0.2f;
        public static float SmallBallVisualizationFadeOutTime = 5f;
        
        // GradientDescent
        public static int MaxNumberOfTrainingSets = 700;
        public static int NumberOfTrainingSetsUsedForXYGD = 6;
        public static int NumberOfTrainingSetsUsedForHeightGD = 3;
        public static int NumberOfGDUpdateCyclesHeight = 2000;
        public static int NumberOfGDUpdateCyclesXY = 1000;
        
        // alpha is what is often referred to as the "learning rate"
        public static float AlphaXY = 0.2f;
        public static float AlphaHeight = 0.6f;

        // Cut level for the "custom gray" in imgMode 7's border tracer. Re-tuned 2026-08-21 for
        // GrayMode 0 (r-b) on the correctly-lit scene by simulating the tracer over live frames:
        // 70 gives exactly ONE object, centre (300,210), r=168.7, blob circularity 0.78 - the best
        // of 15..120. Live stability at this setting: centre +-0.78px, radius +-0.23px over 25
        // frames, cross-checked against HoughCircles which agrees to ~4px.
        // Re-tune this if GrayMode or the lighting changes - the metrics have different ranges.
        public static Byte Threshold = 70;

        public static int PixelSpacing = 30;

        public enum ImgMode
        {
            Src,
            Red,
            Green,
            Blue,
            Normalgray,
            Customgray,
            CustomgrayWithCirclesOverlayed,
            CustomgrayWithInternalImageProcessing
        }

        public static List<string> Captions = new List<string>()
        {
            "RGB",
            "Red Channel",
            "Green Channel",
            "Blue Channel",
            "Normal Grayscale",
            "Orange to Grayscale",
            "Hough Transform Circle Detection",
            "Custom Circle Detection Algorithm"
        };
    }
}
