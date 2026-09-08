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
        [Tooltip("Bottom of the stroke, mm above the working origin, and the tightest the " +
                 "camera's view ever gets during a cycle.\n\n" +
                 "Raising this buys field of view - the camera looks up from below, so a higher " +
                 "plate is further away and sees more of it: +-51.3mm at a 55mm plate against " +
                 "+-57.6mm at 70mm, and the throw is unchanged because it depends on the stroke " +
                 "length rather than the height. That was tried at 50 and reverted, because the " +
                 "trim on this rig is a property of the HEIGHT: moving the base 15mm put the " +
                 "plate somewhere it had never been levelled for, and the ball rolled out of " +
                 "frame before the loop could see it. Re-level at the new base FIRST if you " +
                 "raise this.")]
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

        [Tooltip("OFF (the default): one phase per instruction, so the tilt is recomputed four " +
                 "times a cycle as it is on the PyQt host. The cycle stretches to 0.62s because " +
                 "MachineController charges 50ms after every batch it accepts, and pays it four " +
                 "times instead of once.\n\n" +
                 "ON batches all four phases into one command, which pays that 50ms once and " +
                 "gives a 0.47s cycle - but then ONE tilt is held for the entire cycle, and that " +
                 "is dangerous here. The ball is in contact with the plate for about 0.32s of it, " +
                 "and 3 degrees over 0.32s accelerates it to 116 mm/s and moves it 18mm - in a " +
                 "single cycle, with no chance to correct until the next one. Measured on a real " +
                 "run: the ball crossed the camera's whole window in about a second and was " +
                 "thrown clear. A loop correcting once every 0.47s cannot arrest something it " +
                 "accelerates that hard.\n\n" +
                 "Turn it on only for a gentle stroke, or with the tilt clamp well below 3 " +
                 "degrees. The rhythm it buys is not worth losing the ball.")]
        public bool SendWholeCycleAtOnce = false;

        [Tooltip("Use the ANALYTICAL controller for the rise, and PID for everything else.\n\n" +
                 "They do different jobs at different moments. PID steers a ball that is ROLLING: " +
                 "it accelerates it toward the target while the ball is on the plate. The " +
                 "analytical controller aims a ball that is LEAVING: it sets the plate normal so " +
                 "the bounce sends the ball where you want, and the flight carries it there. " +
                 "Splitting them by phase lets each act where it can, instead of blending two " +
                 "outputs that optimise different things and fight.\n\n" +
                 "Do not expect much of it on this machine, and here is the arithmetic. At 3 " +
                 "degrees the aim adds about 50 mm/s of lateral velocity, and the ball is only " +
                 "airborne 0.064s, so it travels about 3mm. PID over the 0.32s of contact moves " +
                 "it about 19mm. Bounce aiming is roughly six times weaker here purely because " +
                 "the hop is small - it is the technique the original paper's machine used, and " +
                 "that one threw far higher.\n\n" +
                 "It also aims gently rather than wildly: BallData.AirborneTime is clamped to a " +
                 "minimum of 0.1s, so with a real 0.064s flight the controller believes the ball " +
                 "has longer than it does and asks for less lateral speed than it needs. Safe, " +
                 "but biased short.")]
        public bool AimTheThrow = true;

        [Tooltip("How far the ball may drift from the target, in mm, before the throwing stops " +
                 "and the plate goes back to simply balancing it.\n\n" +
                 "This is a CAMERA limit rather than a plate one. The visible half-window is " +
                 "about 51mm at the juggling base, so a ball 30mm out is running out of frame " +
                 "while the plate still has plenty of room. Suspending is also the strongest " +
                 "correction available: tilt cannot move a ball that is in the air, so stopping " +
                 "the throw hands the loop the whole cycle instead of the 0.32s of contact it " +
                 "gets while juggling.")]
        public float SuspendBeyondMm = 30f;

        [Tooltip("How close to the target the ball must come, in mm, before juggling resumes. " +
                 "Deliberately much tighter than SuspendBeyondMm - out past 30mm, back within " +
                 "8mm. That gap is hysteresis, and it is what stops the program chattering " +
                 "across a single boundary.")]
        public float ResumeWithinMm = 8f;

        [Tooltip("And how slow, in mm/s. Position alone is not enough: a ball crossing the middle " +
                 "at speed is momentarily centred, and is the worst possible moment to throw it.")]
        public float ResumeSpeedMmPerSec = 25f;

        [Tooltip("Consecutive commands that must pass both tests before the oscillation restarts, " +
                 "so one lucky frame cannot start it. Eight is about half a second of settled " +
                 "ball.")]
        public int ResumeHoldCommands = 8;

        [Tooltip("OFF: the recovery only ever balances at the bottom of the stroke, which is " +
                 "correct but is also where the camera's window is at its narrowest.\n\n" +
                 "ON: while recovering, the plate holds at the TOP of the stroke instead. The " +
                 "camera looks up from below, so a higher plate is further away and sees more of " +
                 "it - roughly +-51mm at the 35mm base against +-53mm at 51mm. A ball that has " +
                 "drifted out of frame is exactly the case where those extra millimetres decide " +
                 "whether the loop can see what it is chasing.")]
        public bool RecoverAtTopOfStroke = false;
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
            float settleMoveTime, Action onOscillationStart = null,
            ITiltController aimController = null)
        {
            var low = settings.LowMm / 1000f;

            strategies.Add(BallControlStrategyFactory.GoToWhenBallOnPlate(low));

            // Settling is pure position holding, so it always uses the rolling controller. The
            // aiming one has nothing to aim at while the ball is not being thrown.
            strategies.Add(BallControlStrategyFactory.Balancing(
                low, settings.SettleCycles, target, tiltController, settleMoveTime));

            strategies.Add(Cycle(settings, tiltController, target, onOscillationStart,
                                 aimController, settleMoveTime));
        }

        /// <summary>
        /// The oscillation itself.
        /// </summary>
        public static IBallControlStrategy Cycle(OscillatingJugglingSettings settings,
            ITiltController tiltController, Vector2 target, Action action = null,
            ITiltController aimController = null, float recoverMoveTime = 0.06f)
        {
            var low = settings.LowMm / 1000f;
            var high = settings.HighMm / 1000f;
            var recoverHeight = settings.RecoverAtTopOfStroke ? high : low;

            // Supervision state, captured by the lambda below and carried between calls.
            //
            // Without this the oscillation settles the ball once, in the stage before this one,
            // and then throws for ever without looking again - so a ball that drifts keeps being
            // thrown on its way out of the camera's window. On this rig that window is narrow
            // enough that drifting out is a normal event, not an exception.
            //
            // So being centred is a state the cycle keeps re-earning. Lose it and the plate stops
            // throwing and just balances until the ball is settled in the middle again; the
            // throwing then resumes from the start of a stroke.
            var centred = false;
            var settledStreak = 0;

            // Where the plate actually is. Needed because a recovery can interrupt the stroke at
            // any phase, and getting back down has to be done gently.
            var plateHigh = false;

            // Phase is deliberately NOT instructionCount. Recovery commands are instructions too,
            // and counting them would rotate the rise/dwell/fall/dwell sequence by however many
            // it took to get the ball back - leaving the plate rising when it should be falling.
            var phase = 0;

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
                    // An unseen ball is never a centred one. Throwing something you cannot see is
                    // the one thing this must not do, so a dropout costs the resume streak.
                    centred = false;
                    settledStreak = 0;
                    return false;
                }

                var offset = new Vector2(ballData.CurrentPositionVector.x - target.x,
                                         ballData.CurrentPositionVector.y - target.y).magnitude;
                var speed = new Vector2(ballData.CurrentVelocityVector.x,
                                        ballData.CurrentVelocityVector.y).magnitude;

                if (centred && offset > settings.SuspendBeyondMm)
                {
                    centred = false;
                    settledStreak = 0;
                }

                if (!centred)
                {
                    settledStreak = offset <= settings.ResumeWithinMm
                                    && speed <= settings.ResumeSpeedMmPerSec
                        ? settledStreak + 1
                        : 0;

                    if (settledStreak < settings.ResumeHoldCommands)
                    {
                        // Recovering: hold a height and steer with the rolling controller. Never
                        // the aiming one - there is no throw to aim while the ball stays down.
                        var recover = tiltController.CalculateTilt(
                            ballData.CurrentPositionVector,
                            new Vector2(ballData.CurrentVelocityVector.x,
                                        ballData.CurrentVelocityVector.y),
                            target,
                            ballData.CalculatedOnBounceDownwardsVelocity,
                            ballData.AirborneTime);

                        // Getting to the recovery height has to be gentle. A recovery can
                        // interrupt the stroke mid-flight, and moving those 16mm in the 0.06s
                        // balancing time is 2.2g either way: downwards it pulls the plate out from
                        // under the ball, upwards it is simply another throw. Both are the exact
                        // thing being recovered from, so the transition is given the fall time
                        // (0.31g) and only a plate already at the right height uses the fast move.
                        var moving = plateHigh != settings.RecoverAtTopOfStroke;
                        plateHigh = settings.RecoverAtTopOfStroke;
                        phase = 0;

                        machineController.SendInstructions(new List<HLInstruction>()
                        {
                            new HLInstruction(recoverHeight,
                                Mathf.Clamp(recover.xTilt, c.MinTiltAngle, c.MaxTiltAngle),
                                Mathf.Clamp(recover.yTilt, c.MinTiltAngle, c.MaxTiltAngle),
                                moving ? settings.FallTime : recoverMoveTime),
                        });

                        // Recovery does not count toward the cycle total: the program is meant to
                        // run a number of JUGGLES, and a long recovery should not consume them.
                        return false;
                    }

                    // Earned it back. Resume on a rise, from a plate that is already at the
                    // bottom, rather than wherever the stroke happened to be interrupted.
                    centred = true;
                }

                // The rise is the throw - the one phase where the ball leaves the plate, and so
                // the only one an aiming controller can do anything with. Every other phase is
                // the ball rolling, which is the rolling controller's job.
                //
                // Only in per-phase mode: batching sends one tilt for the whole cycle, so there
                // is no separate rise to aim.
                var aiming = settings.AimTheThrow
                             && aimController != null
                             && !settings.SendWholeCycleAtOnce
                             && phase % 4 == 0;

                var tilt = (aiming ? aimController : tiltController).CalculateTilt(
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

                    plateHigh = false;
                    return true;
                }

                float height, moveTime;

                switch (phase % 4)
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

                plateHigh = height == high;
                phase++;
                return true;
            }, duration, onStrategyExecutionStart: action);
        }
    }
}
