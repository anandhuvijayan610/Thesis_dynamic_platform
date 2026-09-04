using System;
using System.Collections.Generic;
using UnityEngine;
using c = HighPrecisionStepperJuggler.Constants;

namespace HighPrecisionStepperJuggler
{
    public static class BallControlStrategyFactory
    {
        // NOTE: the original body of this method ignored lowPos/highPos entirely and hardcoded
        // 0.06f/0.05f, so passing anything else silently did nothing - the swing was always 10mm
        // however this was called. Fixed to actually use the parameters. The defaults are set to
        // exactly what was hardcoded (0.05/0.06), so every EXISTING zero-argument call site keeps
        // behaving identically - only a caller that passes lowPos/highPos explicitly is affected.
        //
        // (The old defaults of 0.5f/0.6f were themselves nonsense - 500mm/600mm plate heights,
        // unreachable by this machine - and were never actually used by any real caller because the
        // hardcoded body ignored them too. Left as evidence should anyone go looking; the real
        // defaults now are the ones that matter.)
        public static IBallControlStrategy Bouncing(int duration, ITiltController tiltController,
            float lowPos = 0.05f, float highPos = 0.06f, float moveTime = 0.1f, Action action = null)
        {
            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                if (ballData.CurrentPositionVector.z < 150f)
                {
                    var tilt = tiltController.CalculateTilt(
                        ballData.CurrentPositionVector,
                        ballData.CurrentVelocityVector,
                        Vector2.zero,
                        ballData.CalculatedOnBounceDownwardsVelocity,
                        ballData.AirborneTime
                    );

                    var xCorrection = Mathf.Clamp(tilt.xTilt, c.MinTiltAngle, c.MaxTiltAngle);
                    var yCorrection = Mathf.Clamp(tilt.yTilt, c.MinTiltAngle, c.MaxTiltAngle);

                    machineController.SendInstructions(new List<HLInstruction>()
                    {
                        new HLInstruction(highPos, xCorrection, yCorrection, moveTime),
                        new HLInstruction(lowPos, 0f, 0f, moveTime),
                    });

                    return true;
                }

                return false;
            }, duration, onStrategyExecutionStart: action);
        }

        public static IBallControlStrategy BouncingStrong(int duration, ITiltController tiltController,
            float lowPos = 0.05f, float highPos = 0.08f, float moveTime = 0.1f, Action action = null)
        {
            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                if (ballData.CurrentPositionVector.z < 190f)
                {
                    var tilt = tiltController.CalculateTilt(
                        ballData.CurrentPositionVector,
                        ballData.CurrentVelocityVector,
                        Vector2.zero,
                        ballData.CalculatedOnBounceDownwardsVelocity,
                        ballData.AirborneTime
                    );

                    var xCorrection = Mathf.Clamp(tilt.xTilt, c.MinTiltAngle, c.MaxTiltAngle);
                    var yCorrection = Mathf.Clamp(tilt.yTilt, c.MinTiltAngle, c.MaxTiltAngle);

                    machineController.SendInstructions(new List<HLInstruction>()
                    {
                        new HLInstruction(highPos, xCorrection, yCorrection, moveTime),
                        new HLInstruction(lowPos, 0f, 0f, moveTime),
                    });

                    return true;
                }

                return false;
            }, duration, onStrategyExecutionStart: action);
        }

        public static IBallControlStrategy StepBouncing_Up(ITiltController tiltController,
            Vector2? target = null, float highPos = 0.058f, float moveTime = 0.1f,
            Action action = null)
        {
            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                if (!ballData.BallIsMovingUp && ballData.CurrentPositionVector.z < 140f )
                {
                    // if we're in here, the ball is coming downwards
                    BallControlling.MoveToHeightWithXYTiltCorrection(machineController, tiltController,
                        ballData, highPos, moveTime, target);

                    return true;
                }
                return false;
            }, 1, true, onStrategyExecutionStart: action);
        }

        public static IBallControlStrategy StepBouncing_Down(ITiltController tiltController,
            Vector2? target = null, float lowPos = 0.05f, float moveTime = 0.1f,
            Action action = null)
        {
            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                if (ballData.BallIsMovingUp)
                {
                    // if we're in here, the ball is moving upwards
                    // so if the ball IS moving up, and the last thing we did was hitting the ball, then we should move down again
                    BallControlling.MoveToHeightWithXYTiltCorrection(machineController, tiltController,
                        ballData, lowPos, moveTime, target);

                    return true;
                }
                return false;
            }, 1, true, onStrategyExecutionStart: action);
        }

        // NOTE: Duration needs to be a multiple of 2 since both the upwards motion and the downwards motion
        //       count as 1 instructionSent
        public static IBallControlStrategy TwoStepBouncing(int duration, ITiltController tiltController,
            Vector2? target = null, float lowPos = 0.05f, float highPos = 0.058f, float moveTime = 0.1f,
            Action action = null)
        {
            var currentPositionIsUp = false;

            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                if (!ballData.BallIsMovingUp && ballData.CurrentPositionVector.z < 140f && !currentPositionIsUp)
                {
                    // if we're in here, the ball is coming downwards

                    BallControlling.MoveToHeightWithAlternatingXYTiltCorrection(machineController, tiltController,
                        ballData, highPos, moveTime, instructionCount, target);

                    currentPositionIsUp = true;
                    return true;
                }

                if (ballData.BallIsMovingUp && currentPositionIsUp)
                {
                    // if we're in here, the ball is moving upwards
                    // so if the ball IS moving up, and the last thing we did was hitting the ball, then we should move down again

                    BallControlling.MoveToHeightWithAlternatingXYTiltCorrection(machineController, tiltController,
                        ballData, lowPos, moveTime, instructionCount, target);

                    currentPositionIsUp = false;
                    return true;
                }

                // instructionSent: false
                return false;
            }, duration, true, onStrategyExecutionStart: action);
        }



        // stable bouncing with shallow plate (not much up down movement)
        public static IBallControlStrategy TwoStepBouncingWithShallowMovement(int duration, ITiltController tiltController,
            Vector2? target, Action action = null)
        {
            return TwoStepBouncing(duration, tiltController, target, 0.05f, 0.054f, 0.06f, action);
        }
        
        // TODO: fix this ControlStrategy. Bouncing isn't stable.
        public static IBallControlStrategy TwoStepBouncingLow(int duration,
            ITiltController tiltController, Vector2? target, Action action = null)
        {
            return TwoStepBouncing(duration, tiltController, target, 0.05f, 0.054f, 0.07f, action);
        }

        /// <summary>
        /// A bounce split into four phases - fast rise, hold, gentle fall, hold - instead of
        /// Bouncing()'s back-to-back rise and fall at one shared move time.
        ///
        /// Two things this fixes, both reported on the real rig as "the whole structure shakes and
        /// the ball gets thrown off":
        ///
        /// 1. Bouncing() runs the FALL at the same speed as the rise, so every cycle contains TWO
        ///    hard accelerations. Only the rise needs to be hard - that is the one that has to beat
        ///    1g to separate the ball. The fall launches nothing, so running it fast is pure
        ///    structural excitation for no benefit. Here the fall gets its own, much longer time.
        ///
        /// 2. Back-to-back strokes make the plate a continuous oscillator, and the frame has time
        ///    to build up rather than damp between hits. The two dwells break that up: they are
        ///    sent as moves to the height the plate is ALREADY at, so the plate genuinely holds
        ///    still while the time passes.
        ///
        /// The four phases are sent as four SEPARATE control cycles, one per call, not as one
        /// four-instruction list. That costs an extra microcontroller margin per phase but it is
        /// what makes the ball stay centred: MachineController.SendInstructions ignores anything
        /// sent while a move list is still running, so a single list means ONE tilt computation for
        /// the whole 0.6s cycle. At a typical 2 degrees that lets the ball drift ~17mm uncorrected
        /// before the next update, against ~1mm in the 0.15s balancing stages - and with only about
        /// +-30mm of frame room, that is most of the plate. Split this way the tilt is recomputed
        /// every phase and the loop rate is back in the range the gains were tuned for.
        ///
        /// The correction is applied on EVERY phase, including the fall and bottom dwell. Those are
        /// the phases where the ball is resting in contact with the plate - about 60% of the cycle -
        /// so they are when a tilt can actually roll it toward the centre. Levelling there (what
        /// Bouncing does, and what this method did originally) throws away most of the available
        /// correction and only makes sense for a ball that is airborne most of the time.
        ///
        /// Use a POSITION-based controller here (PIDTiltController), not AnalyticalTiltController.
        /// The analytical one is a paddle-redirect model: it solves for the plate normal that
        /// reflects an incoming ball toward the target within one airborne time. That needs a real
        /// flight, and this deliberately gentle bounce does not have one - the hop is ~3mm, about
        /// 0.05s, and BallData.AirborneTime floors at 0.1s, so its landing-speed model comes out
        /// ~2x too fast. The tilt it then asks for saturates at MaxTiltAngle for anything more than
        /// ~4mm off centre, and a full 5 degrees applied through the rise flings the ball off the
        /// plate - which is exactly what it did on the rig.
        /// </summary>
        public static IBallControlStrategy RhythmicBouncing(int bounceCycles, ITiltController tiltController,
            Vector2 target, float lowPos, float highPos, float riseTime, float topDwellTime,
            float fallTime, float bottomDwellTime, Action action = null)
        {
            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                if (ballData.CurrentPositionVector.z < 200f)
                {
                    var tilt = tiltController.CalculateTilt(
                        ballData.CurrentPositionVector,
                        new Vector2(ballData.CurrentVelocityVector.x, ballData.CurrentVelocityVector.y),
                        target,
                        ballData.CalculatedOnBounceDownwardsVelocity,
                        ballData.AirborneTime
                    );

                    var xCorrection = Mathf.Clamp(tilt.xTilt, c.MinTiltAngle, c.MaxTiltAngle);
                    var yCorrection = Mathf.Clamp(tilt.yTilt, c.MinTiltAngle, c.MaxTiltAngle);

                    float phaseHeight;
                    float phaseTime;

                    switch (instructionCount % 4)
                    {
                        case 0:
                            phaseHeight = highPos;
                            phaseTime = riseTime;
                            break;
                        case 1:
                            phaseHeight = highPos;
                            phaseTime = topDwellTime;
                            break;
                        case 2:
                            phaseHeight = lowPos;
                            phaseTime = fallTime;
                            break;
                        default:
                            phaseHeight = lowPos;
                            phaseTime = bottomDwellTime;
                            break;
                    }

                    machineController.SendInstructions(new List<HLInstruction>()
                    {
                        new HLInstruction(phaseHeight, xCorrection, yCorrection, phaseTime),
                    });

                    return true;
                }

                return false;
                // Four phases per bounce, so the strategy runs for four times the cycle count.
            }, bounceCycles * 4, onStrategyExecutionStart: action);
        }

        /// <summary>
        /// Balances at <paramref name="height"/> until the ball is settled at the target, then
        /// finishes - see BalancingUntilSettledStrategy for why this is condition-based rather
        /// than a fixed duration.
        ///
        /// "Settled" = within toleranceInMm of the target, moving slower than maxSpeedInMmPerSecond
        /// in 3D, and sitting no more than settledHeightInMm above the plate, for holdCycles
        /// consecutive cycles. maxCycles caps how long it will wait before giving up and moving on.
        /// </summary>
        public static IBallControlStrategy BalancingUntilSettled(float height, Vector2 target,
            ITiltController tiltController, float toleranceInMm, float maxSpeedInMmPerSecond,
            float settledHeightInMm, int holdCycles, int maxCycles, float moveTime = 0.1f,
            Action action = null)
        {
            return new BalancingUntilSettledStrategy(
                (ballData, machineController) =>
                {
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

                    var xCorrection = Mathf.Clamp(tilt.xTilt, c.MinTiltAngle, c.MaxTiltAngle);
                    var yCorrection = Mathf.Clamp(tilt.yTilt, c.MinTiltAngle, c.MaxTiltAngle);

                    machineController.SendInstructions(new List<HLInstruction>()
                    {
                        new HLInstruction(height, xCorrection, yCorrection, moveTime),
                    });

                    return true;
                },
                ballData =>
                {
                    var position = ballData.CurrentPositionVector;

                    // z is the ball's height above the WORKING ORIGIN, while height is the plate's,
                    // so the gap between them is how far the ball is off the plate - which is what
                    // separates "resting" from "still bouncing".
                    var heightAbovePlate = position.z - height * 1000f;

                    return new Vector2(position.x - target.x, position.y - target.y).magnitude <= toleranceInMm
                           && ballData.CurrentVelocityVector.magnitude <= maxSpeedInMmPerSecond
                           && heightAbovePlate <= settledHeightInMm;
                },
                holdCycles,
                maxCycles,
                action);
        }

        public static IBallControlStrategy Balancing(float height, int duration, Vector2 target,
            ITiltController tiltController, float moveTime = 0.1f, Action action = null)
        {
            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                if (ballData.CurrentPositionVector.z < float.MaxValue)
                {
                    var tilt = tiltController.CalculateTilt(
                        ballData.CurrentPositionVector,
                        new Vector2(ballData.CurrentVelocityVector.x, ballData.CurrentVelocityVector.y),
                        target,
                        ballData.CalculatedOnBounceDownwardsVelocity,
                        ballData.AirborneTime);

                    var xCorrection = Mathf.Clamp(tilt.xTilt, c.MinTiltAngle, c.MaxTiltAngle);
                    var yCorrection = Mathf.Clamp(tilt.yTilt, c.MinTiltAngle, c.MaxTiltAngle);

                    machineController.SendInstructions(new List<HLInstruction>()
                    {
                        new HLInstruction(height, xCorrection, yCorrection, moveTime),
                    });

                    return true;
                }

                return false;
            }, duration, onStrategyExecutionStart: action);
        }

        public static IBallControlStrategy GoTo(float height, float time = 0.5f, Action action = null)
        {
            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                machineController.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(height, 0f, 0f, time),
                });
                return true;
            }, 1, onStrategyExecutionStart: action);
        }

        public static IBallControlStrategy GoToWhenBallOnPlate(float height, float time = 0.5f, Action action = null)
        {
            return new BallControlStrategy((ballData, machineController, instructionCount) =>
            {
                if (ballData.CurrentPositionVector.z < 200f)
                {
                    machineController.SendInstructions(new List<HLInstruction>()
                    {
                        new HLInstruction(height, 0f, 0f, time),
                    });
                    return true;
                }

                return false;
            }, 1, onStrategyExecutionStart: action);
        }
    }
}
