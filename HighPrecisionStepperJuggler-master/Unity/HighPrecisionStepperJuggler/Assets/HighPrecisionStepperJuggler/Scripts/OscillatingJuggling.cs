using System;
using System.Collections.Generic;
using UnityEngine;
using c = HighPrecisionStepperJuggler.Constants;

namespace HighPrecisionStepperJuggler
{
    /// <summary>
    /// Settings for the fixed four-phase juggle, mirroring the PyQt host's Juggling mode.
    ///
    /// Heights are millimetres ABOVE THE WORKING ORIGIN, the same reference the rest of the
    /// program uses - the working origin is itself Constants.OriginHeightOffset above the
    /// mechanical dead position.
    /// </summary>
    [Serializable]
    public class OscillatingJugglingSettings
    {
        [Tooltip("Bottom of the stroke, mm above the working origin. The ball is caught here.")]
        public float LowMm = 35f;

        [Tooltip("Top of the stroke, mm above the working origin. Stroke length is the knob for " +
                 "how high the ball hops: 16mm gives about 6mm of clearance, 20mm about 11mm, " +
                 "25mm about 20mm and is more than the loop can catch.")]
        public float HighMm = 51f;

        [Tooltip("The stroke that throws the ball, at the firmware's 0.05s floor. With a 16mm " +
                 "stroke that is 3.2g, and the ball separates part way up carrying 0.48 m/s.")]
        public float RiseTime = 0.05f;

        [Tooltip("Held at the top while the ball is airborne, so it lands on a stationary plate. " +
                 "Matched to the flight - about 0.064s for the 16mm stroke.")]
        public float TopDwellTime = 0.07f;

        [Tooltip("Deliberately slower than the rise. The fall launches nothing, so speed here is " +
                 "structural excitation for no benefit.")]
        public float FallTime = 0.16f;

        [Tooltip("Where most of the steering happens: tilt cannot move a ball that is in the " +
                 "air, so the time it spends on a stationary plate is the only authority the " +
                 "loop has.")]
        public float BottomDwellTime = 0.14f;

        [Tooltip("Cycles to run before the program moves on. Large values effectively mean " +
                 "'until disarmed'.")]
        public int Cycles = 10000;

        [Tooltip("Balancing cycles at the bottom of the stroke before any bouncing starts. The " +
                 "oscillation aims each hit using where the ball already is, so if it cannot be " +
                 "settled first, bouncing will not settle it.")]
        public int SettleCycles = 15;

        [Tooltip("ON: the whole four-phase cycle goes out as ONE batch, so the firmware runs the " +
                 "phases back to back. MachineController adds 50ms after each batch it accepts, " +
                 "and batching pays that once per cycle instead of four times: 0.47s per cycle " +
                 "rather than 0.62s, against the PyQt host's 0.50s. The cost is that tilt is " +
                 "chosen once per cycle instead of at every phase boundary.\n\n" +
                 "OFF: one phase per instruction, so tilt is recomputed four times a cycle as it " +
                 "is on the PyQt host - but the cycle stretches to 0.62s and the plate then " +
                 "waits at the top nearly twice as long as the ball is actually airborne, which " +
                 "is what makes the rhythm feel wrong.")]
        public bool SendWholeCycleAtOnce = true;
    }

    /// <summary>
    /// A fixed four-phase juggle: fast rise, dwell, gentle fall, dwell, repeat.
    ///
    /// This is a port of the PyQt host's Juggling mode, and it is deliberately a different shape
    /// from SmallJugglingDemo. That one is a staged choreography whose stages advance on what the
    /// ball is doing; this one is a clock. Only the rise needs to beat 1g - that is what separates
    /// the ball - and the tilt correction rides on top of every phase, including the contact ones,
    /// because those are when tilt can actually roll the ball toward the centre.
    ///
    /// Added as a separate program rather than by changing the existing ones, so both remain
    /// available: pick between them with the Strategy Program dropdown.
    /// </summary>
    public static class OscillatingJuggling
    {
        /// <summary>
        /// Builds the whole program: wait for the ball, rise, settle, then oscillate.
        /// </summary>
        public static void AddTo(List<IBallControlStrategy> strategies,
            OscillatingJugglingSettings settings, ITiltController tiltController, Vector2 target,
            float settleMoveTime, Action onOscillationStart = null)
        {
            var low = settings.LowMm / 1000f;

            strategies.Add(BallControlStrategyFactory.GoToWhenBallOnPlate(low));

            strategies.Add(BallControlStrategyFactory.Balancing(
                low, settings.SettleCycles, target, tiltController, settleMoveTime));

            strategies.Add(Cycle(settings, tiltController, target, onOscillationStart));
        }

        /// <summary>
        /// The oscillation itself.
        /// </summary>
        public static IBallControlStrategy Cycle(OscillatingJugglingSettings settings,
            ITiltController tiltController, Vector2 target, Action action = null)
        {
            var low = settings.LowMm / 1000f;
            var high = settings.HighMm / 1000f;

            // One instruction per phase, or one per whole cycle - the strategy finishes on a
            // count, so the count has to be expressed in whatever unit is actually being sent.
            var duration = settings.SendWholeCycleAtOnce
                ? settings.Cycles
                : settings.Cycles * 4;

            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                // No ball, no instruction - and deliberately no count either, so a dropout does
                // not silently eat cycles. ImageProcessingInstructionSender's ball-lost timer is
                // what decides when a loss becomes an abort.
                if (ballData.CurrentPositionVector.z >= float.MaxValue)
                {
                    return false;
                }

                var tilt = tiltController.CalculateTilt(
                    ballData.CurrentPositionVector,
                    new Vector2(ballData.CurrentVelocityVector.x, ballData.CurrentVelocityVector.y),
                    target,
                    ballData.CalculatedOnBounceDownwardsVelocity,
                    ballData.AirborneTime);

                var xTilt = Mathf.Clamp(tilt.xTilt, c.MinTiltAngle, c.MaxTiltAngle);
                var yTilt = Mathf.Clamp(tilt.yTilt, c.MinTiltAngle, c.MaxTiltAngle);

                if (settings.SendWholeCycleAtOnce)
                {
                    // A dwell is a move to the height the plate is already at, so it genuinely
                    // holds still rather than drifting.
                    machineController.SendInstructions(new List<HLInstruction>()
                    {
                        new HLInstruction(high, xTilt, yTilt, settings.RiseTime),
                        new HLInstruction(high, xTilt, yTilt, settings.TopDwellTime),
                        new HLInstruction(low, xTilt, yTilt, settings.FallTime),
                        new HLInstruction(low, xTilt, yTilt, settings.BottomDwellTime),
                    });

                    return true;
                }

                float height, moveTime;

                switch (instructionCount % 4)
                {
                    case 0:
                        height = high;
                        moveTime = settings.RiseTime;
                        break;
                    case 1:
                        height = high;
                        moveTime = settings.TopDwellTime;
                        break;
                    case 2:
                        height = low;
                        moveTime = settings.FallTime;
                        break;
                    default:
                        height = low;
                        moveTime = settings.BottomDwellTime;
                        break;
                }

                machineController.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(height, xTilt, yTilt, moveTime),
                });

                return true;
            }, duration, onStrategyExecutionStart: action);
        }
    }
}
