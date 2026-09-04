using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;

namespace HighPrecisionStepperJuggler
{
    public class RealMachine : InstructableMachine
    {
        [SerializeField] private SerialInterface _serial = null;

        // Echo every line sent to the Teensy into the Console.
        //
        // Worth turning on whenever this host's behaviour is being compared against the PyQt
        // one: both build the wire line from the same kinematics, so with the same origin
        // offset, pairing and trim they must emit byte-identical text. That single comparison
        // proves the whole chain - IK, arm pairing, origin subtraction and levelling trim - in
        // one step, and localises any difference to the settings rather than the maths.
        //
        // Off by default because a juggling run sends about twenty lines a second and the
        // Console cannot keep up.
        [SerializeField] private bool _logSentLines = false;
        
        protected override void SendInstructions(List<LLInstruction> diffInstructions)
        {
            var builder = new StringBuilder();
            int i = 1;

            foreach (var diffInstruction in diffInstructions)
            {
                if (i >= 2) builder.Append(":");

                builder.Append((11f * i++).ToString("0.00000", CultureInfo.InvariantCulture));
                builder.Append(":");
                builder.Append(diffInstruction.Serialize());
            }

            builder.Append('\n');

            _serial.Send(builder.ToString());

            if (_logSentLines)
            {
                Debug.Log($"[RealMachine] TX {builder.ToString().TrimEnd()}");
            }
        }

        private void Update()
        {
            if (_serial == null)
            {
                return;
            }

            // Runtime test: press T to send a visible single-motor move for debugging
            if (Input.GetKeyDown(KeyCode.T))
            {
                Debug.Log("[RealMachine] Sending test move (motor0, small rotation, 2s)");
                _serial.SendTestMove(0, 0.1f, 2f);
            }

            // Runtime test: press Y to send a ping and receive a response from the Teensy
            if (Input.GetKeyDown(KeyCode.Y))
            {
                Debug.Log("[RealMachine] Sending ping to Teensy");
                _serial.SendPing();
            }
        }

        public override void GoToOrigin()
        {
            SendInstructions(new List<LLInstruction>() {new LLInstruction(Constants.ZeroMachineState, 1f)});
        }
    }
}
