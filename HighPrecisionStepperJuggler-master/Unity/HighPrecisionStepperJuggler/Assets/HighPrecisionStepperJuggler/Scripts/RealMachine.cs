using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;

namespace HighPrecisionStepperJuggler
{
    public class RealMachine : InstructableMachine
    {
        [SerializeField] private SerialInterface _serial = null;
        
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
            
            //debug.Log($"Sent to serial: {builder.ToString()}"); //debug for seeing what is being sent to the serial interface
        }

        private void Update()
        {
            // Runtime test: press T to send a visible single-motor move for debugging
            if (Input.GetKeyDown(KeyCode.T))
            {
                if (_serial != null)
                {
                    Debug.Log("[RealMachine] Sending test move (motor0, small rotation, 2s)");
                    _serial.SendTestMove(0, 0.1f, 2f);
                }
                else
                {
                    Debug.LogWarning("_serial is null");
                }
            }
        }

        public override void GoToOrigin()
        {
            SendInstructions(new List<LLInstruction>() {new LLInstruction(Constants.ZeroMachineState, 1f)});
        }
    }
}
