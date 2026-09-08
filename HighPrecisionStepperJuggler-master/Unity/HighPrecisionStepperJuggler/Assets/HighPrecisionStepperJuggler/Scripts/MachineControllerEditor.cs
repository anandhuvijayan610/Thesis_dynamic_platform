using System.Collections.Generic;
using UnityEditor;
#if UNITY_EDITOR
using UnityEngine;

namespace HighPrecisionStepperJuggler
{
    [CustomEditor(typeof(MachineController))]
    public class MachineControllerEditor : Editor
    {
        public override void OnInspectorGUI()
        {
            DrawDefaultInspector();

            var script = (MachineController) target;

            if (GUILayout.Button("Go to origin", GUILayout.Width(200)))
            {
                script.GoToOrigin();
            }

            if (GUILayout.Button("Go to mechanical zero", GUILayout.Width(200)))
            {
                script.GoToMechanicalZero();
            }

            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Level the plate at origin", EditorStyles.boldLabel);

            var step = script.LevelTrimStepDegrees;

            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.LabelField("X", GUILayout.Width(14));
            if (GUILayout.Button("-", GUILayout.Width(88)))
            {
                script.NudgeLevelTrim(-1f, 0f);
            }

            if (GUILayout.Button("+", GUILayout.Width(88)))
            {
                script.NudgeLevelTrim(1f, 0f);
            }

            EditorGUILayout.LabelField($"X {script.LevelTrimX:0.00} deg");
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.LabelField("Y", GUILayout.Width(14));
            if (GUILayout.Button("-", GUILayout.Width(88)))
            {
                script.NudgeLevelTrim(0f, -1f);
            }

            if (GUILayout.Button("+", GUILayout.Width(88)))
            {
                script.NudgeLevelTrim(0f, 1f);
            }

            EditorGUILayout.LabelField($"Y {script.LevelTrimY:0.00} deg");
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Reset trim to zero", GUILayout.Width(180)))
            {
                script.ResetLevelTrim();
            }

            if (GUILayout.Button("Re-send origin", GUILayout.Width(180)))
            {
                script.ApplyInspectorLevelTrim();
                script.GoToOrigin();
            }
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.HelpBox(
                $"Each nudge moves the trim by {step:0.00} deg and re-sends the origin pose, so " +
                "adjust with a spirit level on the plate and watch it settle. The offset is then " +
                "added to every command, including the control loop's, so a level plate here " +
                "means the controller's zero is the real zero.\n\n" +
                "Trim X first: tilting one pair changes how level the other looks. Re-level after " +
                "changing the working origin - the trim is a property of the height, not of the " +
                "machine.\n\n" +
                "TO KEEP A VALUE: type it into the Level Trim X/Y Degrees fields at the top " +
                "of this inspector and save the scene (Ctrl+S). Those are [SerializeField]s, so " +
                "once the scene has stored them THEY are what runs - Awake() copies them over " +
                "Constants.LevelTrimXDegrees, and editing Constants.cs will not change anything " +
                "for a scene that already has them. The constants are only the fallback for a " +
                "scene that has never serialized the field.\n\n" +
                "The nudge buttons change the live value and the fields, but a value only " +
                "survives play mode if the scene is saved.",
                MessageType.None);

            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Backlash test", EditorStyles.boldLabel);

            var d = script.BacklashTestTiltDegrees;

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("X +" + d + " deg", GUILayout.Width(90)))
            {
                script.SendTiltTest(d, 0f);
            }

            if (GUILayout.Button("X level", GUILayout.Width(90)))
            {
                script.SendTiltTest(0f, 0f);
            }

            if (GUILayout.Button("X -" + d + " deg", GUILayout.Width(90)))
            {
                script.SendTiltTest(-d, 0f);
            }
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Y +" + d + " deg", GUILayout.Width(90)))
            {
                script.SendTiltTest(0f, d);
            }

            if (GUILayout.Button("Y level", GUILayout.Width(90)))
            {
                script.SendTiltTest(0f, 0f);
            }

            if (GUILayout.Button("Y -" + d + " deg", GUILayout.Width(90)))
            {
                script.SendTiltTest(0f, -d);
            }
            EditorGUILayout.EndHorizontal();

            if (GUILayout.Button("Reversal cycle x5 (play mode)", GUILayout.Width(200)))
            {
                script.RunTiltReversalCycle(5);
            }

            EditorGUILayout.Space();

            if (GUILayout.Button("Go to height: 10mm", GUILayout.Width(200)))
            {
                script.SendSingleInstruction(new HLInstruction(0.01f, 0f, 0f, 0.15f));
            }

            if (GUILayout.Button("Go to height: 20mm", GUILayout.Width(200)))
            {
                script.SendSingleInstruction(new HLInstruction(0.02f, 0f, 0f, 0.15f));
            }

            if (GUILayout.Button("20mm tilt right left", GUILayout.Width(200)))
            {
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.02f, 0.1f, 0f, 0.3f),
                    new HLInstruction(0.02f, -0.1f, 0f, 0.3f)
                });
            }

            if (GUILayout.Button("20mm tilt right 1 degree", GUILayout.Width(200)))
            {
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.02f, 1f, 0f, 0.2f),
                });
            }

            if (GUILayout.Button("20mm tilt right 2 degree", GUILayout.Width(200)))
            {
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.02f, 2f, 0f, 0.2f),
                });
            }
            
            if (GUILayout.Button("20mm tilt right 3 degree", GUILayout.Width(200)))
            {
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.02f, 3f, 0f, 0.2f),
                });
            }

            if (GUILayout.Button("20mm tilt right 3 deg, front 3 deg", GUILayout.Width(200)))
            {
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.02f, 3f, 3f, 0.2f),
                });
            }

            if (GUILayout.Button("20mm tilt front back", GUILayout.Width(200)))
            {
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.02f, 0.0f, 0.1f, 0.3f),
                    new HLInstruction(0.02f, 0.0f, -0.1f, 0.3f)
                });
            }

            if (GUILayout.Button("demo", GUILayout.Width(200)))
            {
                var moveTime = 0.3f;
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.02f, 0.0f, 0.1f, moveTime),
                    new HLInstruction(0.02f, 0.0f, -0.1f, moveTime),
                    new HLInstruction(0.02f, 0.1f, 0f, moveTime),
                    new HLInstruction(0.02f, -0.1f, 0f, moveTime),
                    new HLInstruction(0.02f, 0.0f, 0.1f, moveTime),
                    new HLInstruction(0.02f, 0.0f, -0.1f, moveTime),
                    new HLInstruction(0.02f, 0.1f, 0f, moveTime),
                    new HLInstruction(0.02f, -0.1f, 0f, moveTime),
                    new HLInstruction(0.03f, 0.0f, 0f, moveTime),
                    new HLInstruction(0.04f, 0.0f, 0f, moveTime),
                });
            }

            if (GUILayout.Button("demo 0.2", GUILayout.Width(200)))
            {
                var moveTime = 0.2f;
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.02f, 0.0f, 0.1f, moveTime),
                    new HLInstruction(0.02f, 0.0f, -0.1f, moveTime),
                    new HLInstruction(0.02f, 0.1f, 0f, moveTime),
                    new HLInstruction(0.02f, -0.1f, 0f, moveTime),
                    new HLInstruction(0.02f, 0.0f, 0.1f, moveTime),
                    new HLInstruction(0.02f, 0.0f, -0.1f, moveTime),
                    new HLInstruction(0.02f, 0.1f, 0f, moveTime),
                    new HLInstruction(0.02f, -0.1f, 0f, moveTime),
                    new HLInstruction(0.03f, 0.0f, 0f, moveTime),
                    new HLInstruction(0.04f, 0.0f, 0f, moveTime),
                });
            }

            if (GUILayout.Button("demo 0.1", GUILayout.Width(200)))
            {
                var moveTime = 0.1f;
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.02f, 0.0f, 0.1f, moveTime),
                    new HLInstruction(0.02f, 0.0f, -0.1f, moveTime),
                    new HLInstruction(0.02f, 0.1f, 0f, moveTime),
                    new HLInstruction(0.02f, -0.1f, 0f, moveTime),
                    new HLInstruction(0.02f, 0.0f, 0.1f, moveTime),
                    new HLInstruction(0.02f, 0.0f, -0.1f, moveTime),
                    new HLInstruction(0.02f, 0.1f, 0f, moveTime),
                    new HLInstruction(0.02f, -0.1f, 0f, moveTime),
                    new HLInstruction(0.03f, 0.0f, 0f, moveTime),
                    new HLInstruction(0.04f, 0.0f, 0f, moveTime),
                });
            }

            if (GUILayout.Button("flex", GUILayout.Width(200)))
            {
                var moveTime = 0.3f;
                var tilt = 0.06694f;
                script.SendInstructions(new List<HLInstruction>()
                {
                    new HLInstruction(0.09f, 0.0f, 0.0f, 0.5f),
                    new HLInstruction(0.01f, 0.0f, 0.0f, 0.5f),
                    new HLInstruction(0.02f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.03f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.04f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.05f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.06f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.07f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.09f, 0f, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, -tilt, 0.0f, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.08f, -tilt, 0.0f, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.01f, tilt, 0.0f, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.08f, tilt, 0.0f, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.01f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, -tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, tilt, 0.0f, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0f, -tilt, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.08f, 0f, -tilt, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0f, tilt, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.08f, 0f, tilt, 0.5f, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0f, -tilt, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, 0f, -tilt, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0f, tilt, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.08f, 0f, tilt, moveTime, isFlexInstruction: true),
                    new HLInstruction(0.01f, 0.0f, 0.0f, 0.5f),
                    new HLInstruction(0.05f, 0.0f, 0.0f, 0.5f),
                });
            }
        }
    }
}
#endif
