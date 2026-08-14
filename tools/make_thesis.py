#!/usr/bin/env python3
# Rebuilds Thesis_Draft.docx (expanded draft with equations, figures, photos, TODO markers).
# Requirements: python-docx, and the figures fig_ik.png / fig_sine.png / fig_fov.png /
# fig_block.png (regenerate with gen_figs.py + gen_block.py if missing).
# Paths: set THESIS_DIR to the Thesis folder and FIG_DIR to where the fig_*.png files are.
import os
import docx
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

THESIS = os.environ.get("THESIS_DIR", "/sessions/elegant-nifty-thompson/mnt/Thesis/")
GEN = os.environ.get("FIG_DIR", "/sessions/elegant-nifty-thompson/mnt/outputs/")
IMG = THESIS + "my_documents/images/"
DIA = THESIS + "my_documents/connection diagrams/"

FONT = "Arial"
RED = RGBColor(0xC0, 0x00, 0x00)
BLACK = RGBColor(0, 0, 0)

doc = Document()

st = doc.styles["Normal"]
st.font.name = FONT
st.font.size = Pt(11)
st.paragraph_format.line_spacing = 1.5
st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
st.paragraph_format.space_after = Pt(6)

for name, size in [("Heading 1", 14), ("Heading 2", 12), ("Heading 3", 11)]:
    hs = doc.styles[name]
    hs.font.name = FONT
    hs.font.size = Pt(size)
    hs.font.bold = True
    hs.font.color.rgb = BLACK
    hs.paragraph_format.line_spacing = 1.5
    hs.paragraph_format.space_before = Pt(12)
    hs.paragraph_format.space_after = Pt(6)
    hs.element.get_or_add_rPr()

sec = doc.sections[0]
sec.top_margin = Cm(2.5); sec.bottom_margin = Cm(2.5)
sec.left_margin = Cm(3); sec.right_margin = Cm(2)

fp = sec.footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
run = fp.add_run()
f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin")
it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = "PAGE"
f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "end")
run._r.append(f1); run._r.append(it); run._r.append(f2)
run.font.name = FONT; run.font.size = Pt(10)

def p(text, italic=False, bold=False, color=None, align=None, size=11):
    par = doc.add_paragraph()
    if align is not None:
        par.alignment = align
    r = par.add_run(text)
    r.font.name = FONT; r.font.size = Pt(size); r.italic = italic; r.bold = bold
    if color: r.font.color.rgb = color
    return par

def todo(text):
    return p("[TODO: " + text + "]", italic=True, color=RED)

def h1(text, pagebreak=True):
    if pagebreak:
        doc.add_page_break()
    par = doc.add_heading(text, level=1)
    for r in par.runs:
        r.font.name = FONT; r.font.color.rgb = BLACK; r.font.size = Pt(14)
    return par

def h2(text):
    par = doc.add_heading(text, level=2)
    for r in par.runs:
        r.font.name = FONT; r.font.color.rgb = BLACK; r.font.size = Pt(12)
    return par

def h3(text):
    par = doc.add_heading(text, level=3)
    for r in par.runs:
        r.font.name = FONT; r.font.color.rgb = BLACK; r.font.size = Pt(11)
    return par

def bullet(text):
    par = doc.add_paragraph(style="List Bullet")
    par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = par.add_run(text)
    r.font.name = FONT; r.font.size = Pt(11)
    return par

def eq(text, num):
    par = doc.add_paragraph()
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = par.add_run(text + "        (" + num + ")")
    r.font.name = FONT; r.font.size = Pt(11); r.italic = True
    return par

def fig(path, caption, width_cm=14):
    if not os.path.exists(path):
        return todo("MISSING FIGURE: " + path + " — " + caption)
    par = doc.add_paragraph()
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = par.add_run()
    run.add_picture(path, width=Cm(width_cm))
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = cap.add_run(caption)
    r.font.name = FONT; r.font.size = Pt(10)
    return par

# ---------- Title page ----------
p("", align=WD_ALIGN_PARAGRAPH.CENTER)
for _ in range(4): doc.add_paragraph()
p("Deggendorf Institute of Technology — Campus Cham", align=WD_ALIGN_PARAGRAPH.CENTER, size=12)
doc.add_paragraph()
p("Master Thesis", align=WD_ALIGN_PARAGRAPH.CENTER, size=14)
p("Development of a Multi-Actuated Platform for Dynamic Ball Manipulation",
  align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, size=18)
doc.add_paragraph()
p("Anandhu Vijayan", align=WD_ALIGN_PARAGRAPH.CENTER, size=12)
p("[Matriculation number | Degree programme | Supervisor | Date]",
  align=WD_ALIGN_PARAGRAPH.CENTER, italic=True, color=RED)
p("DRAFT — replace this title page with the official DIT template (guideline A2)",
  align=WD_ALIGN_PARAGRAPH.CENTER, italic=True, color=RED, size=10)

# ---------- Abstract ----------
h1("Abstract")
p("This thesis describes the development of a multi-actuated platform for dynamic ball manipulation. Based on the open-source Octo-Bouncer concept, a four-arm parallel kinematic platform was reconstructed and adapted using modified, commercially available hardware: geared NEMA 17 stepper motors driven by DM542T digital drivers, a Teensy 4.0 microcontroller, a 120 fps USB machine-vision camera, and a redesigned power and signal architecture comprising an XL4016 step-down converter and a TXS0108E bidirectional level shifter. A machine-vision pipeline based on OpenCV detects the ball position at 120 frames per second, and an inverse-kinematics-based control loop implemented in Unity commands the plate motion via a serial protocol. Substantial modifications to the reference firmware and communication layer were required and are documented systematically. The resulting system was evaluated with respect to detection performance, motion fidelity and ball manipulation capability.")
todo("Finalize abstract to 120-150 words once results are available; add keywords.")

# ---------- TOC ----------
h1("Table of Contents")
par = doc.add_paragraph()
r = par.add_run()
f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin"); f1.set(qn("w:dirty"), "true")
it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve")
it.text = 'TOC \\o "1-3" \\h \\z \\u'
f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "separate")
t = OxmlElement("w:t"); t.text = "Right-click and select 'Update Field' to generate the table of contents."
f3 = OxmlElement("w:fldChar"); f3.set(qn("w:fldCharType"), "end")
r._r.append(f1); r._r.append(it); r._r.append(f2); r._r.append(t); r._r.append(f3)
r.font.name = FONT; r.font.size = Pt(11)

# ---------- Indexes ----------
h1("Index of Abbreviations")
for line in ["DIT — Deggendorf Institute of Technology", "DOF — Degrees of Freedom",
             "FOV — Field of View", "FPS — Frames per Second",
             "GPIO — General Purpose Input/Output", "IK — Inverse Kinematics",
             "ISR — Interrupt Service Routine", "PID — Proportional-Integral-Derivative (controller)",
             "PSU — Power Supply Unit", "UVC — USB Video Class"]:
    p(line)
todo("Complete alphabetically; add formula symbol index (L1, L2, q, theta1, theta2, y, T, etc.).")

# ================= CHAPTER 1 =================
h1("1 Introduction")
h2("1.1 Motivation")
p("Keeping a ball bouncing on an actuated plate is a classic benchmark problem in mechatronics: it couples fast optical perception, real-time state estimation, inverse kinematics and closed-loop control in a single system whose failure modes are immediately visible. While industrial ball-and-plate demonstrators typically stabilise a rolling ball, dynamic ball manipulation — controlling a ball that repeatedly leaves and re-contacts the plate — imposes considerably harder requirements on latency, actuator acceleration and measurement accuracy.")
h2("1.2 State of the art")
p("Robotic ball juggling and batting has been studied both with industrial manipulators and with dedicated mechanisms. Rapp demonstrated a real-time vision-guided framework for catching and juggling ping-pong balls with an industrial robot arm [3]. Reist and D'Andrea showed that a blind juggling robot can bounce an unconstrained ball in three dimensions without any ball sensing, relying purely on passive stability of the paddle motion [4]. Jia et al. analysed the mechanics of batting an in-flight object to a target [2], and Ji et al. recently presented a vision-based table-tennis juggling robot with experimental validation [1]. In the maker domain, the Octo-Bouncer by T. Kuhn [5] demonstrated that a four-arm stepper-driven platform combined with 120 fps machine vision can produce highly repeatable bouncing patterns; its software is available as the open-source HighPrecisionStepperJuggler project [6]. The present work builds on this reference design.")
h2("1.3 Objective and task definition")
p("The objective of this thesis is the development and commissioning of a multi-actuated platform for dynamic ball manipulation. The reference design is to be reconstructed and adapted to hardware that is commercially available and economically reasonable, which requires a re-selection of the camera, the stepper drivers and the power and signal-interface architecture, corresponding mechanical adaptations, and a systematic revision of firmware and communication software. The resulting system is to be evaluated with respect to perception performance, motion fidelity and ball manipulation capability.")
h2("1.4 Delimitation from the reference work")
p("The kinematic concept, the Unity-based host application and the firmware architecture originate from the open-source reference project [6]. The following contributions were made within this thesis: selection and evaluation of alternative components (camera and lens, DM542T drivers, XL4016 buck converter, TXS0108E level shifter, geared NEMA 17 motors) including alternatives that were tested and rejected; design of the complete power and signal architecture; mechanical adaptation of the arms and the camera mounting; correction of the firmware motion constants and pulse generation for the modified drive train; redesign of the PC-side serial communication layer; and the complete integration, commissioning and experimental evaluation of the machine.")
h2("1.5 Structure of the thesis")
p("Chapter 2 summarises the required fundamentals. Chapter 3 covers the system design and the selection of all components. Chapter 4 describes the software implementation and the modifications to the reference software. Chapter 5 documents the integration, commissioning and troubleshooting. Chapter 6 presents the results, and Chapter 7 concludes with a summary and prospects.")

# ================= CHAPTER 2 =================
h1("2 Fundamental Principles")

h2("2.1 Kinematics of the four-arm plate manipulator")
p("The platform is a parallel kinematic mechanism in which four identical arms, arranged at 90° intervals around the base, jointly position the plate. Each arm is a planar two-link mechanism: the lower link of length L₁ = 89 mm is mounted on the motor shaft, and the upper link of length L₂ = 80 mm connects to a joint on the underside of the plate. By construction, the plate joint of each arm is constrained to move on a vertical line at the fixed horizontal distance q = 70.0 mm from the motor axis. The plate thus possesses three controlled degrees of freedom: vertical translation and rotation about the two horizontal axes (tilt). Figure 2.1 shows the geometry of a single arm.")
fig(GEN + "fig_ik.png", "Figure 2.1: Geometry of one arm. The plate joint is constrained to the vertical line x = q; the motor angle θ₁ determines the plate height y.", 11)
p("With the motor angle θ₁ measured against the horizontal, the height y of the plate joint follows from the two link lengths and the lateral constraint:")
eq("y(θ₁) = L₁ sin θ₁ + √( L₂² − (q − L₁ cos θ₁)² )", "2.1")
p("The rotation of the second joint follows directly from the same geometry:")
eq("θ₂ = π − arccos( (L₁ cos θ₁ − q) / L₂ )", "2.2")
p("For control, the inverse relation is required: the motor angle θ₁ that produces a commanded height y. Equation (2.1) was solved for θ₁ in closed form using a computer algebra system; the implementation evaluates θ₁ = ±arccos(a₁(a₂ − a₃)), where a₁, a₂ and a₃ are polynomial expressions in L₁, L₂, q and y, and the sign is selected by comparing the commanded height with the height at θ₁ = 0. A tilted plate additionally shifts the effective lateral distance of each plate joint; this is handled by a per-arm correction q → q + Δq (the \"q-offset\"), which is recomputed from the commanded tilt in every control cycle. Commanding the four arms with heights derived from the desired plate pose (height plus two tilt angles) therefore positions the plate without any additional sensors, since stepper motors track their commanded angle open-loop.")
todo("Reproduce the full closed-form expression for θ₁ (from InverseKinematic.cs) as a numbered equation, and add the derivation of the q-offset from the tilt angles (MachineController/HLInstruction).")

h2("2.2 Stepper motors, gearboxes and motion profile")
p("Hybrid stepper motors divide one revolution into 200 full steps. Microstepping drivers subdivide each full step electronically, improving resolution and smoothness at the cost of holding torque per microstep. A planetary gearbox increases output torque and angular resolution by its transmission ratio while reducing maximum output speed. For the drive train used here (5.18:1 gearbox, 1/16 microstepping) one output revolution corresponds to")
eq("N = 200 · 16 · 5.18 = 16 576 pulses per output revolution", "2.3")
p("so that 500 pulses correspond to approximately 10.9° of output-shaft rotation.")
p("To avoid exciting resonances and to limit jerk, the firmware executes every move with a sinusoidal velocity profile. With move duration T and pulse count Δs, an internal phase θ(t) = πt/T advances once per timer interrupt, and the emitted position follows")
eq("x(t) = Δs · (1 − cos θ(t)) / 2,   0 ≤ t ≤ T", "2.4")
p("The resulting step rate is sinusoidal, vanishing at the start and end of the move and peaking at the midpoint:")
eq("ẋ(t) = (Δs · π / 2T) · sin(πt/T),   ẋₘₐₓ = πΔs / 2T", "2.5")
p("For a representative balancing move of 500 pulses in T = 0.1 s the peak step rate is approximately 7 854 pulses per second (Figure 2.2). The firmware generates these pulses in a timer interrupt with a 10 µs period; since one step requires two interrupt ticks (pin toggle), the achievable ceiling is approximately 25 000 pulses per second, leaving a factor of three of headroom over the peak demand.")
fig(GEN + "fig_sine.png", "Figure 2.2: Sinusoidal motion profile of a 500-pulse move executed in 0.1 s. Position (solid) and step rate (dashed).", 13)

h2("2.3 Power electronics and level translation")
p("Buck (step-down) converters transfer energy from a higher input voltage to a regulated lower output voltage via a switched inductor; relevant selection parameters are input voltage range, continuous output current and efficiency. Digital logic families operating at different supply voltages (here 3.3 V on the microcontroller and 5 V on the driver inputs) require level translation; bidirectional translators such as the TXS0108E use one-shot accelerated pass transistors per channel.")
todo("Elaborate: buck converter operating principle with schematic; TXS0108E channel architecture from the datasheet.")

h2("2.4 Machine vision for ball detection")
p("The ball is observed by a single camera mounted above the plate. The image processing pipeline must deliver the three-dimensional ball position at the full camera frame rate of 120 fps, since the ball state between bounces is airborne for only a few hundred milliseconds. Classical circle detection with the Hough transform is robust in cluttered scenes but exhibits considerable position and radius noise and is computationally too expensive at 120 fps [5][7]; the reference project therefore introduced an edge-following detector that traces the contour of bright pixel regions and estimates the ball diameter from the largest pairwise contour distances.")
p("The third dimension is recovered from the apparent ball size. With the ball radius R = 20 mm, the horizontal camera resolution W = 640 pixels and the horizontal field of view α = 61.6°, a detected ball radius of r pixels corresponds to a distance between ball and plate of")
eq("d = R / tan( (r/W) · α ) − h₀", "2.6")
p("where h₀ = 78 mm is the height of the ball resting on the plate at the machine origin. The lateral position follows from the pixel offset p from the image centre:")
eq("X = tan( (α/2) · p / (W/2) ) · (d + h₀)", "2.7")
p("applied analogously in both image axes (Figure 2.3). The ball velocity is estimated from the sequence of reconstructed positions by gradient descent over a sliding window, which smooths the frame-to-frame noise sufficiently for impact prediction.")
fig(GEN + "fig_fov.png", "Figure 2.3: Camera geometry above the plate. The apparent ball radius yields the height via equation (2.6); the pixel offset yields the lateral position via equation (2.7).", 11)
todo("Important adaptation: the software constant CameraFOVInDegrees = 61.6° corresponds to the reference camera. The lens used here has 56° horizontal FOV — recalibrate this constant and document the calibration measurement.")

h2("2.5 Control of a bouncing ball")
p("Sections to elaborate: PID control of the ball position; analytical tilt control based on mirror-law reflection of the incoming velocity vector; prediction of the impact position; limitations arising from surface irregularities and ball spin.", italic=True)
h2("2.6 System software architecture")
p("Sections to elaborate: division of labour between the PC application (perception, state estimation, IK, control, visualisation) and the microcontroller firmware (pulse generation in a timer ISR); serial communication over USB CDC; consequences of the PC side not receiving hardware acknowledgements.", italic=True)

# ================= CHAPTER 3 =================
h1("3 System Design and Component Selection")
h2("3.1 Overall system concept")
p("The system consists of a USB camera observing the plate from above, a PC application performing image processing, state estimation, control and inverse kinematics, and a Teensy 4.0 microcontroller that converts received motion instructions into step pulses for four stepper drivers. Figure 3.1 shows the complete signal and power architecture: the camera streams into the Unity application, motion instructions travel over USB serial to the Teensy, its 3.3 V step/direction signals are translated to 5 V by the TXS0108E and drive the four DM542T stepper drivers, which power the geared NEMA 17 motors actuating the plate. The drivers are supplied directly from a 35 V / 8 A power supply unit, while an XL4016 buck converter derives the 5 V rail for the driver logic inputs and the level shifter. All components are mounted on a plywood base board that carries the aluminium frame, the drivers and the electronics.")
fig(GEN + "fig_block.png", "Figure 3.1: System architecture. Top: signal chain from camera to motors. Bottom: power distribution and the optical feedback loop closing via the camera.", 16)
h2("3.2 Requirements")
bullet("Ball position measurement at 120 fps with sufficient accuracy for velocity estimation.")
bullet("Plate accelerations sufficient to keep a ping-pong ball bouncing (reference: four-arm design of [5]).")
bullet("Drive resolution fine enough for smooth, low-vibration plate motion.")
bullet("Electrical compatibility between the 3.3 V microcontroller and 5 V driver inputs.")
bullet("All components commercially available at reasonable cost.")
todo("Quantify: latency budget, required plate acceleration, positioning resolution.")

h2("3.3 Actuation")
h3("3.3.1 Motor selection")
p("NEMA 17 hybrid stepper motors with an integrated 5.18:1 planetary gearbox were selected. The gearbox raises the available output torque and increases the angular resolution to 0.35° per full step at the output shaft, at the cost of maximum output speed. A standard (non-geared) NEMA 17 was considered as an alternative; its higher speed could not compensate for the reduced torque reserve and coarser effective resolution for this application.")
todo("Add torque calculation for the arm linkage and cite both motor datasheets; state the exact motor part numbers.")
h3("3.3.2 Driver selection: DM542T")
p("The DM542T is a digital stepper driver with a supply range of 20–50 V DC, adjustable output current and fifteen selectable microstep resolutions (400 to 25 600 pulses per revolution). It accepts step/direction signals and performs internal current regulation with anti-resonance features. In this work the driver is operated from the 35 V supply at 1/16 microstepping, yielding 3 200 pulses per motor revolution and, with the 5.18:1 gearbox, 16 576 pulses per output revolution (equation 2.3). Compared with compact driver ICs used in the reference design, the DM542T provides higher current reserves, robust optocoupler inputs and DIP-switch configuration, at the cost of requiring 5 V logic-level signals — a requirement that motivated the level-shifting stage described in Section 3.6.")
h2("3.4 Vision system")
h3("3.4.1 Camera selection")
p("The reference project used an e-con Systems SEE3CAM_CU135 [5]. Owing to availability and cost, an ELP 12 MP USB camera with UVC support and an exchangeable M12 lens was selected instead. The camera supports the frame rates and manual parameter control (exposure, gain, brightness, saturation) required by the image processing pipeline and delivers 640 × 480 pixel image data at 120 fps in the configuration used.")
todo("State exact sensor model and confirm the achieved format/fps from the final configuration.")
h3("3.4.2 Lens selection")
p("The camera observes the plate from a short distance, therefore the lens must combine a wide field of view — so that the ball remains in frame over the full plate area and bounce height — with a large depth of field, so that the ball stays acceptably focused over its trajectory. An M12 lens with 4.3 mm focal length and f/2.8 aperture was selected, providing a diagonal field of view of 67° (56° horizontal). The 12 mm narrow-angle lens supplied with the camera was rejected: it produces a larger image of the ball but its field of view of approximately 25° cannot cover the plate at the available mounting distance, and it exhibits a shallower depth of field at close range.")
todo("Add a sketch of the FOV/working-distance geometry derived from the real camera mounting distance (do not reuse the AI-generated comparison diagram from the working notes).")
h2("3.5 Power supply architecture")
p("The four DM542T drivers are supplied directly from a 35 V / 8 A power supply unit. A separate 5 V rail is required for the driver logic inputs and the high-voltage side of the level shifter. Two step-down solutions were evaluated. The Joy-IT SBC-Buck02 module (9–35 V input, fixed 5 V output) was tested first but was rejected on power-rating grounds: the 35 V system supply lies at the very limit of its specified input range, leaving no operating margin, and its output power rating is insufficient for the architecture. It was replaced by an XL4016-based converter module with 5–40 V input, adjustable 1.25–35 V output and up to 8 A output current, which tolerates the 35 V supply with margin and provides ample current reserve.")
todo("Add the measured load on the 5 V rail.")
h2("3.6 Signal-level interfacing: TXS0108E")
p("The Teensy 4.0 operates its GPIO at 3.3 V and is not 5 V tolerant, whereas the optocoupler inputs of the DM542T are specified for 5 V signals. A TXS0108E 8-bit bidirectional level shifter therefore translates the step and direction signals from the 3.3 V domain to 5 V. Eight channels accommodate the four step and four direction lines of the drivers. The 5 V side is supplied from the XL4016 rail (Section 3.5).")
todo("Add note on signal integrity/edge rates at the maximum step frequency (~25 kHz) and the wiring layout.")
h2("3.7 Mechanical design")
p("The mechanical concept follows the reference design: four motor-driven arms, arranged around the base, carry the plate via upper links. Within this thesis the arm geometry was re-modelled in Fusion 360 (lower and upper arm, upper links) and manufactured additively; the joints run on ball bearings (6 mm bore, 12 mm outer diameter) with stainless-steel spacers, and aluminium profiles form the frame. The bouncing surface is an octagonal plate of 8 mm transparent acrylic glass with a side length of 82.8 mm. A camera frame and holder were designed to mount the camera above the plate at the working distance required by the lens geometry (Section 3.4.2).")
p("The entire structure is mounted on an 8 mm plywood base board (550 mm × 390 mm) to which the frame, the motor assemblies, the drivers and the remaining electronics are fastened. The mounting holes were drilled with an 8 mm twist drill; for plywood of this thickness, moderate spindle speeds (approximately 1 500–2 500 rpm) were used to avoid tearing the veneer layers and overheating the bit, and clean hole entry was ensured before fastening the components with M3 machine screws and nuts.")
fig(IMG + "assemblem.jpeg", "Figure 3.2: Assembled platform: four geared NEMA 17 motors with 3D-printed arms carrying the plate; electronics mounted on the plywood base board.", 9)
todo("Insert CAD renders and drawing references (Design/, stl files/); state print materials/settings and tolerances.")
h2("3.8 Wiring and bill of materials")
p("Figure 3.3 shows the wiring of the Teensy 4.0 to the four DM542T drivers via the level shifter; the complete finalized connection diagram is provided in the Appendix. Table 3.1 summarises the main components.")
fig(DIA + "teensy_4driver_wiring.png", "Figure 3.3: Wiring of the Teensy 4.0 step/direction outputs to the four DM542T drivers via the TXS0108E level shifter.", 15)
p("Table 3.1: Main components of the platform", italic=True)

rows = [
    ["Component", "Type / Model", "Purpose", "Qty", "Price (EUR)"],
    ["Microcontroller", "Teensy 4.0 (600 MHz, ARM Cortex-M7), with pins", "Firmware, step-pulse generation", "1", "31.89"],
    ["Stepper motors", "StepperOnline NEMA 17 with 5.18:1 planetary gearbox", "Plate actuation via four arms", "4", "110.76"],
    ["Stepper drivers", "DM542T digital driver", "Microstepping drive of the motors", "4", "86.04"],
    ["Power supply", "35 V / 8 A DC", "Main supply for motor drivers", "1", "-"],
    ["Buck converter", "XL4016 step-down module (5-40 V in, max. 8 A)", "5 V rail for driver logic / level shifter", "1", "-"],
    ["Level shifter", "TXS0108E 8-bit bidirectional (AZ-Delivery)", "3.3 V (Teensy) to 5 V (driver inputs)", "1", "-"],
    ["Camera", "ELP 12 MP USB (UVC), 120 fps, M12 mount", "Ball position measurement", "1", "126.00"],
    ["Lens", "M12, 4.3 mm, f/2.8, FOV 67° diag. / 56° horiz.", "Field of view covering the plate", "1", "-"],
    ["Plate", "Octagonal acrylic glass, 8 mm, side length 82.8 mm", "Bouncing surface", "1", "-"],
    ["Base board", "Plywood, 550 mm × 390 mm × 8 mm", "Mounting of frame and electronics", "1", "-"],
    ["Ball bearings", "6 mm bore / 12 mm outer diameter", "Arm joints", "12+", "-"],
    ["Spacers", "Stainless steel, 3 mm bore / 6 mm outer, 5 mm length", "Arm joints", "12+", "-"],
    ["Fasteners", "M3 × 16 / M3 × 20 screws, M3 nuts", "Assembly", "-", "-"],
    ["Frame / misc.", "Aluminium profiles, 3D-printed arms and camera mount, connectors, wiring", "Mechanical structure, cabling", "-", "-"],
    ["Ball", "Table-tennis ball (40 mm)", "Manipulated object", "1", "-"],
]
tbl = doc.add_table(rows=len(rows), cols=5)
tbl.style = "Table Grid"
tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
widths = [Cm(3.0), Cm(5.2), Cm(4.2), Cm(1.2), Cm(1.6)]
for i, row in enumerate(rows):
    for j, text in enumerate(row):
        c = tbl.cell(i, j)
        c.width = widths[j]
        cp = c.paragraphs[0]
        cp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        cr = cp.add_run(text)
        cr.font.name = FONT; cr.font.size = Pt(10); cr.bold = (i == 0)
doc.add_paragraph()
todo("Fill in the missing prices and add supplier references; the full purchase list with links exists in my_documents/octa_bouncer_purchase_links.xlsx (recorded partial total: 354.69 EUR).")

# ================= CHAPTER 4 =================
h1("4 Software Implementation")
h2("4.1 Architecture overview")
p("The software consists of three parts: the Unity host application (image processing control, state estimation, control loop, inverse kinematics, visualisation), a C++ camera plugin executing all OpenCV code, and the Teensy firmware generating step pulses in a timer interrupt. Motion commands are transmitted as ASCII strings of colon-separated values over USB serial and decoded by the firmware into move batches, which the interrupt routine executes as sinusoidal motion profiles (Section 2.2).")
h2("4.2 Image processing pipeline")
p("To elaborate: camera configuration via the UVC plugin; conversion to grayscale; ball detection; 3D position reconstruction via equations (2.6)/(2.7); velocity estimation. Screenshots of the detection stages exist as figure material (see Section 5.3).", italic=True)
h2("4.3 Inverse kinematics and control")
p("To elaborate: IK implementation per Section 2.1; PID and analytical tilt control; hit-position prediction.", italic=True)
h2("4.4 Redesign of the PC-side serial communication layer")
p("The original implementation received serial data on a dedicated background thread. This design caused reliability problems on Windows: blocking read calls, race conditions between sender and receiver threads, and COM ports remaining open when the Unity editor left play mode, which prevented reconnection. The serial interface was therefore restructured to be fully single-threaded. Incoming bytes are polled from Unity's main-thread update loop using non-blocking reads, accumulated in a buffer and split into complete newline-terminated messages before being processed. Outgoing messages are explicitly flushed after writing, and a defined close routine — discarding both buffers and disposing the port — is invoked whenever the application stops, guaranteeing that the COM port is released. Any I/O error closes the port cleanly so that a subsequent send re-opens it instead of leaving the connection in an undefined state.")
h2("4.5 Culture-invariant number formatting")
p("The motion instructions are ASCII strings of decimal numbers. The original serialisation used the operating system's regional number format; on a system with German locale this produces a decimal comma, which the firmware parser cannot interpret — the parsed values silently became zero and the motors never received a usable target. All numeric formatting in the protocol was therefore changed to culture-invariant formatting, ensuring an identical wire format regardless of the host locale. This constituted a root-cause fix for a complete, silent failure of the command chain.")
h2("4.6 Diagnostic instrumentation of the Unity–Teensy link")
p("To localise faults in the chain (serialisation → USB serial → firmware parsing → pulse generation), logging was added at every stage. On the PC side, every transmitted and received message is logged, detected COM ports are listed at startup, and a port-probing utility identifies access conflicts. Two runtime test commands transmit a known single-motor move and a loopback test message. On the firmware side, the Teensy echoes every raw message and prints the parsed tokens, the number of decoded move batches, the batch-marker validation result and the final pulse counts per motor. A standalone test sketch replicating the exact protocol was additionally written to exercise the motor drive path in isolation. This end-to-end trace made it possible to confirm that communication and parsing were correct and that the remaining faults lay in the motion parameters and pulse generation (Section 4.7). It should be noted that the loopback test is realised by the general echo of received messages rather than a dedicated ping handler.")
h2("4.7 Correction of motion parameters and pulse generation")
p("Table 4.1 summarises the firmware timing and scaling constants before and after the corrections described below.")
p("Table 4.1: Firmware constants of the modified system", italic=True)
rows2 = [
    ["Constant", "Reference value", "Corrected value", "Meaning"],
    ["PULSES_PER_REV", "132 608", "16 576", "Pulses per output revolution (eq. 2.3)"],
    ["TIMER_US", "2 µs (orig.) / 100 µs (interm.)", "10 µs", "ISR period"],
    ["FREQUENCY_MULTIPLIER", "0.000002 / 0.00001", "0.00001", "ISR period in seconds (must equal TIMER_US)"],
    ["MOVE_DURATION", "1.0 s / 2.0 s clamp", "0.05 s floor", "Minimum allowed move duration"],
    ["PULSES_TO_MOVE", "4 000", "500", "Self-test move (rescaled to new PULSES_PER_REV)"],
]
tbl2 = doc.add_table(rows=len(rows2), cols=4)
tbl2.style = "Table Grid"
widths2 = [Cm(4.6), Cm(3.6), Cm(2.6), Cm(4.4)]
for i, row in enumerate(rows2):
    for j, text in enumerate(row):
        c = tbl2.cell(i, j)
        c.width = widths2[j]
        cp = c.paragraphs[0]
        cr = cp.add_run(text)
        cr.font.name = FONT; cr.font.size = Pt(10); cr.bold = (i == 0)
doc.add_paragraph()
h3("4.7.1 Steps-per-revolution correction")
p("The firmware constants were still configured for the reference author's drive train (26.85:1 gearbox, 25 600 microsteps per revolution, i.e. 132 608 pulses per output revolution). The actual hardware uses a 5.18:1 geared NEMA 17 with the DM542T set to 1/16 microstepping, i.e. 16 576 pulses per output revolution. With the old constant every commanded angle was scaled eight times too large, demanding step rates the driver could not follow. The constant was corrected and the self-test move rescaled accordingly.")
h3("4.7.2 Interrupt timing correction")
p("Step pulses are generated in a timer interrupt whose period must equal the frequency-multiplier constant used in the trajectory calculation (Section 2.2). The original 2 µs period left insufficient headroom on the modified system, and an intermediate configuration (100 µs period with a multiplier corresponding to 10 µs) caused every move to take ten times its requested duration. The period was set to 10 µs with a consistent multiplier, permitting peak rates of approximately 25 000 steps per second.")
h3("4.7.3 Move-duration floor")
p("A minimum move duration of 0.05 s was introduced: incoming instructions with shorter durations are clamped, protecting the mechanism from physically impossible acceleration demands while remaining below the 0.1 s corrective moves transmitted during balancing. An earlier configuration of 2.0 s had stretched every balancing move to two seconds and, combined with the timing mismatch, to twenty — rendering the motion visually indistinguishable from standstill.")
h3("4.7.4 Direction-reversal bug")
p("The sinusoidal pulse generator derived the step signal from a doubled step count using unsigned arithmetic. For moves in the negative direction the intermediate value is negative; converting a negative floating-point value to an unsigned integer saturates to zero on the Cortex-M7, so counterclockwise moves emitted no pulses at all. The calculation was rewritten with signed arithmetic and an explicit correction for negative remainders.")
h3("4.7.5 Stale-batch handling and pre-emption")
p("When a new instruction packet arrives, the firmware now discards all previously queued move batches and aborts any in-flight move, so that outdated target positions can no longer execute after new ones arrive. Previously, the reset routine only rewound the batch index while the execution flag and phase counter kept running: the interrupt routine continued pulsing toward the old goal, the fresh first batch was never loaded, and stale batches from earlier messages could fire with outdated positions. Because the position counter tracks actually emitted pulses, aborting mid-move remains safe. The mode variable shared with the interrupt routine was additionally declared volatile.")

# ================= CHAPTER 5 =================
h1("5 System Integration and Commissioning")
h2("5.1 Incremental bring-up strategy")
p("The system was commissioned in deliberately small increments, each with a dedicated test sketch: a single-motor test, a test of all four motors, fixed predefined moves, and finally serially commanded motion driven from Unity — first with a protocol-replicating standalone sketch and then with the full firmware. This staging separated electrical faults from firmware faults and firmware faults from host-software faults.")
h2("5.2 Electrical integration")
p("The wiring was built up in iterations. The initial breadboard-based wiring served to verify the level shifter and a single driver; the finalized wiring routes all four step/direction pairs through the TXS0108E to the DM542T inputs, with the XL4016 providing the 5 V rail (Figure 5.1). The driver DIP switches were configured for 1/16 microstepping and the rated motor current.")
fig(IMG + "intial wiring.jpeg", "Figure 5.1a: Initial bring-up wiring of Teensy, level shifter and drivers.", 8)
fig(IMG + "final connection.jpeg", "Figure 5.1b: Finalized wiring of the drive electronics.", 8)
todo("Add the DIP-switch settings actually used (current, microstep) and the 5 V rail measurement.")
h2("5.3 Camera integration and calibration")
p("The camera was configured for 640 × 480 pixels at 120 fps with manual exposure and gain. Two detection approaches were compared during commissioning: colour-based circle detection on the raw image and detection on the grayscale-converted image (Figure 5.2). The grayscale pipeline proved more robust against illumination changes and is the basis of the final detection stage.")
fig(IMG + "color circle detection (1).png", "Figure 5.2a: Colour-based circle detection during commissioning.", 12)
fig(IMG + "gray circle detection.png", "Figure 5.2b: Circle detection on the grayscale-converted image.", 12)
todo("Add the final exposure/gain values and a figure of a detection failure case (material: error_.png, videos).")
h2("5.4 Troubleshooting: the 'motors not moving' fault chain")
p("A central commissioning problem was that the physical machine did not move although the simulation behaved correctly. The systematic diagnosis proceeded in three stages. First, the diagnostic instrumentation (Section 4.6) proved the entire communication chain intact: the firmware received, parsed and echoed correct pulse counts. Second, the fault was thereby localised to the pulse-generation path. Third, four stacked firmware defects were identified and corrected (Section 4.7): the unsigned-arithmetic direction bug suppressing all negative moves, the timing-constant mismatch slowing every move tenfold, the two-second duration clamp stretching 0.1 s commands, and the missing pre-emption that prevented new commands from ever loading. In combination, commanded corrective moves executed at approximately 1.7 degrees per second of output shaft — imperceptible to the eye — while half of them emitted no pulses at all. After applying all four corrections the motors followed commanded motion at the requested speed in both directions.")
p("A locale-dependent number-formatting fault (Section 4.5) had earlier produced a complete silent failure of the command chain on a German-locale host and was resolved as a precondition for the above diagnosis. Figure 5.3 shows the logged ball position and instruction stream used during this diagnosis.")
fig(IMG + "balllog position.png", "Figure 5.3: Logged ball position data and instruction transmission during commissioning.", 16)
h2("5.5 Test design for evaluation")
bullet("Ball detection: achieved frame rate, position noise, detection failures (log plots available).")
bullet("Motion fidelity: commanded versus executed move duration and angle; bidirectional motion.")
bullet("Closed loop: balancing stability, bounce repeatability.")
todo("Define concrete metrics and measurement procedures with the supervisor before evaluation.")

# ================= CHAPTER 6 =================
h1("6 Results")
p("To be written in past tense once measurements are complete: vision performance (6.1), platform motion performance (6.2), ball manipulation results (6.3), comparison with the reference system (6.4, as a table), measurement inaccuracies and their effects (6.5).", italic=True)
todo("Insert measured data; existing material: ball position logs, motion recordings.")

# ================= CHAPTER 7 =================
h1("7 Summary and Prospects")
p("To be written last: summary answering the task definition (7.1), critical reflection (7.2), outlook — advanced bouncing patterns, multi-ball detection, improved control (7.3).", italic=True)

# ================= Bibliography =================
h1("Bibliography")
for ref in [
 "[1] Ji, Y., Zhang, B., Mao, Y., Wang, H., Hu, X., & Zhang, L. (2024). Design, Modeling, and Experimental Validation of a Vision-Based Table Tennis Juggling Robot. Mathematics, 12(11), 1634. https://doi.org/10.3390/math12111634",
 "[2] Jia, Y.-B., Gardner, M., & Mu, X. (2019). Batting an in-flight object to the target. The International Journal of Robotics Research, 38(4), 451-485. https://doi.org/10.1177/0278364918817116",
 "[3] Rapp, H. H. (2011). A ping-pong ball catching and juggling robot: A real-time framework for vision guided acting of an industrial robot arm. The 5th International Conference on Automation, Robotics and Applications. https://doi.org/10.1109/icara.2011.6144922",
 "[4] Reist, P., & D'Andrea, R. (2009). Bouncing an Unconstrained Ball in Three Dimensions with a Blind Juggling Robot. 2009 IEEE International Conference on Robotics and Automation, 1774-1781. https://doi.org/10.1109/robot.2009.5152616",
 "[5] Kuhn, T. (2020). The Octo-Bouncer / The Octo-Bouncer: Advanced Bouncing Patterns. Electron Dust. https://www.electrondust.com [accessed on 18.07.2026]",
 "[6] Kuhn, T. HighPrecisionStepperJuggler (source code). GitHub. https://github.com/T-Kuhn/HighPrecisionStepperJuggler [accessed on 18.07.2026]",
 "[7] OpenCV documentation: Hough Circle Transform. https://docs.opencv.org [accessed on 18.07.2026]",
]:
    p(ref)
todo("Add datasheet references (DM542T, XL4016, TXS0108E, Teensy 4.0, motors, camera) and Chapter 2 textbooks; align citation style (numbered, DIN-conform) with the supervisor.")

# ================= Appendix =================
h1("Appendix")
for line in ["A1 Registration form", "A2 Complete wiring and connection diagrams",
             "A3 Key datasheet pages of the final components",
             "A4 Mechanical drawings (lower arm, upper arm)",
             "A5 Additional logs and measurement data"]:
    p(line)
p("Program code is provided on the electronic data carrier and is not printed.", italic=True)

out = THESIS + "Thesis_Draft.docx"
doc.save(out)
print("written:", out)
