//----------------------------------------------------------------------------------------------------------------------+
// WiiBalanceWalker v0.5, by Shachar Liberman
// Originally Released by Richard Perry from GreyCube.com - Under the Microsoft Public License.
//
// released for windows 10 x64 systems, x86 should be supported too.
//
// Uses lshachar's WiimoteLib DLL:                  https://github.com/lshachar/WiimoteLib
// Uses the 32Feet.NET bluetooth DLL:               http://32feet.codeplex.com/
// Uses vJoy device driver (by Shaul Eizikovich):   http://vjoystick.sourceforge.net/site/index.php/download-a-install/download
// (Previous to WiiBalanceWalker v0.5
//  VJoy by headsoft was used)                      http://headsoft.com.au/index.php?category=vjoy
//----------------------------------------------------------------------------------------------------------------------+

using System;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text.RegularExpressions;
using System.Text;
using System.Threading;
using System.Diagnostics;
using System.Timers;
using System.Windows.Forms;
using InputManager;
using WiimoteLib;

namespace WiiBalanceWalker
{
    public partial class FormMain : Form
    {
        // WinForms Timer runs on the UI thread, so InfoUpdate can refresh the
        // labels without BeginInvoke queue buildup. 20 ms targets 50 Hz.
        System.Windows.Forms.Timer infoUpdateTimer = new System.Windows.Forms.Timer() { Interval = 20, Enabled = false };
        System.Timers.Timer joyResetTimer   = new System.Timers.Timer() { Interval = 240000, Enabled = false };

        ActionList actionList = new ActionList();
        Wiimote wiiDevice     = new Wiimote();
        DateTime jumpTime     = DateTime.UtcNow;
        long wiimoteEventCount = 0;
        long wiimoteEventWindowStart = DateTime.UtcNow.Ticks;

        // Direct telemetry path: WiiBalanceWalker -> Python backend.
        // This is independent from vJoy and from Unity's WASD input mapping.
        const int telemetryPort = 5005;
        readonly UdpClient telemetryClient = new UdpClient();
        readonly IPEndPoint telemetryEndpoint = new IPEndPoint(IPAddress.Loopback, telemetryPort);
        long telemetrySequence = 0;
        readonly object telemetryLock = new object();
        System.Threading.Timer telemetrySendTimer;
        bool hasTelemetrySnapshot = false;
        double latestRawTL, latestRawTR, latestRawBL, latestRawBR;

        readonly string controlInstanceId = Guid.NewGuid().ToString("D");
        long controlSequence = 0;
        readonly Stopwatch controlAgeClock = Stopwatch.StartNew();
        readonly object controlSnapshotLock = new object();
        ControlTelemetrySnapshot latestControlSnapshot = new ControlTelemetrySnapshot();
        bool lastControlBoardValid;
        long centerGeneration = 0;

        bool setCenterOffset = false;
        bool resetCenterOffsetPossible = false;

        float naCorners     = 0f;
        float oaTopLeft     = 0f;
        float oaTopRight    = 0f;
        float oaBottomLeft  = 0f;
        float oaBottomRight = 0f;

        sealed class ControlTelemetrySnapshot
        {
            public bool Valid;
            public bool? ActionsEnabled, JoystickEnabled;
            public bool? RequestedLeft, RequestedRight, RequestedForward, RequestedBackward;
            public bool? IssuedLeft, IssuedRight, IssuedForward, IssuedBackward;
            public string KeyLeft, KeyRight, KeyForward, KeyBackward;
            public double? BalanceX, BalanceY, TriggerLr, TriggerFb;
            public long? CenterGeneration;
            public bool? CenterApplied, BoardLoaded;
            public double? OffsetTl, OffsetTr, OffsetBl, OffsetBr, CornerFloor;
            public string Event;
            public long? Sequence;
            public long TimestampTicks, CaptureAgeMilliseconds;
        }

        public FormMain()
        {
            InitializeComponent();
            telemetrySendTimer = new System.Threading.Timer(
                TelemetryTimerCallback, null, Timeout.Infinite, Timeout.Infinite);
        }

        private void FormMain_Load(object sender, EventArgs e)
        {
            // Setup a timer which controls the rate at which updates are processed.

            infoUpdateTimer.Tick += new EventHandler(infoUpdateTimer_Tick);

            // Load trigger settings.

            numericUpDown_TLR.Value  = Properties.Settings.Default.TriggerLeftRight;
            numericUpDown_TFB.Value  = Properties.Settings.Default.TriggerForwardBackward;
            numericUpDown_TMLR.Value = Properties.Settings.Default.TriggerModifierLeftRight;
            numericUpDown_TMFB.Value = Properties.Settings.Default.TriggerModifierForwardBackward;

            // Link up form controls with action settings.

            actionList.Left          = new ActionItem("Left",          comboBox_AL,  numericUpDown_AL);
            actionList.Right         = new ActionItem("Right",         comboBox_AR,  numericUpDown_AR);
            actionList.Forward       = new ActionItem("Forward",       comboBox_AF,  numericUpDown_AF);
            actionList.Backward      = new ActionItem("Backward",      comboBox_AB,  numericUpDown_AB);
            actionList.Modifier      = new ActionItem("Modifier",      comboBox_AM,  numericUpDown_AM);
            actionList.Jump          = new ActionItem("Jump",          comboBox_AJ,  numericUpDown_AJ);
            actionList.DiagonalLeft  = new ActionItem("DiagonalLeft",  comboBox_ADL, numericUpDown_ADL);
            actionList.DiagonalRight = new ActionItem("DiagonalRight", comboBox_ADR, numericUpDown_ADR);

            // Load saved preference.

            checkBox_SendCGtoXY.Checked = Properties.Settings.Default.SendCGtoXY;
            checkBox_Send4LoadSensors.Checked = Properties.Settings.Default.Send4LoadSensors;
            checkBox_ShowValuesInConsole.Checked = Properties.Settings.Default.ShowValuesInConsole;
            checkBox_EnableJoystick.Checked = Properties.Settings.Default.EnableJoystick;
            checkBox_DisableActions.Checked = Properties.Settings.Default.DisableActions;
            checkBox_StartupAutoConnect.Checked = Properties.Settings.Default.StartupAutoConnect;
            checkBox_AutoTare.Checked = Properties.Settings.Default.AutoTare;
            checkBox_StartMinimized.Checked = Properties.Settings.Default.StartMinimized;

            if (checkBox_StartupAutoConnect.Checked)
            { 
                button_Connect.PerformClick();
            }

            if (checkBox_StartMinimized.Checked)
            {
                this.WindowState = FormWindowState.Minimized;
            }
        }

        private void numericUpDown_TLR_ValueChanged(object sender, EventArgs e)
        {
            Properties.Settings.Default.TriggerLeftRight = (int)numericUpDown_TLR.Value;
            Properties.Settings.Default.Save();
        }

        private void numericUpDown_TFB_ValueChanged(object sender, EventArgs e)
        {
            Properties.Settings.Default.TriggerForwardBackward = (int)numericUpDown_TFB.Value;
            Properties.Settings.Default.Save();
        }

        private void numericUpDown_TMLR_ValueChanged(object sender, EventArgs e)
        {
            Properties.Settings.Default.TriggerModifierLeftRight = (int)numericUpDown_TMLR.Value;
            Properties.Settings.Default.Save();
        }

        private void numericUpDown_TMFB_ValueChanged(object sender, EventArgs e)
        {
            Properties.Settings.Default.TriggerModifierForwardBackward = (int)numericUpDown_TMFB.Value;
            Properties.Settings.Default.Save();
        }

        private void button_SetCenterOffset_Click(object sender, EventArgs e)
        {
            if (resetCenterOffsetPossible && wiiDevice.WiimoteState.BalanceBoardState.WeightKg <= 5)
            {
                naCorners = 0f;
                oaTopLeft = 0f;
                oaTopRight = 0f;
                oaBottomLeft = 0f;
                oaBottomRight = 0f;
                centerGeneration++;
                button_SetCenterOffset.Enabled = false;
                resetCenterOffsetPossible = false;
                PublishInvalidControlSnapshot("center_reset", true);
                button_SetCenterOffset.Text = "Set current balance as center";
                //toolTip1.SetToolTip(button_SetCenterOffset, "While standing or sitting on the balance board, click this button to set your current balance point as center");
            }

            else
            { 
                setCenterOffset = true;
                //toolTip1.SetToolTip(button_SetCenterOffset, "Revert back to the original center balance point, for the X/Y controls");
            }
        }

        private void button_ResetDefaults_Click(object sender, EventArgs e)
        {
            Properties.Settings.Default.Reset();
            this.Close();
        }

        private void button_BluetoothAddDevice_Click(object sender, EventArgs e)
        {
            var form = new FormBluetooth();
            form.ShowDialog(this);
        }

        private void button_Connect_Click(object sender, EventArgs e)
        {
            try
            {
                // Find all connected Wii devices.

                var deviceCollection = new WiimoteCollection();
                deviceCollection.FindAllWiimotes();

                for (int i = 0; i < deviceCollection.Count; i++)
                {
                    wiiDevice = deviceCollection[i];

                    // Device type can only be found after connection, so prompt for multiple devices.

                    if (deviceCollection.Count > 1)
                    {
                        var devicePathId = new Regex("e_pid&.*?&(.*?)&").Match(wiiDevice.HIDDevicePath).Groups[1].Value.ToUpper();

                        var response = MessageBox.Show("Connect to HID " + devicePathId + " device " + (i + 1) + " of " + deviceCollection.Count + " ?", "Multiple Wii Devices Found", MessageBoxButtons.YesNoCancel);
                        if (response == DialogResult.Cancel) return;
                        if (response == DialogResult.No) continue;
                    }

                    // Setup update handlers.

                    wiiDevice.WiimoteChanged          += wiiDevice_WiimoteChanged;
                    wiiDevice.WiimoteExtensionChanged += wiiDevice_WiimoteExtensionChanged;

                    // Connect and send a request to verify it worked.

                    wiiDevice.Connect();
                    // Request continuous balance-board reports so the 20 ms
                    // telemetry timer receives fresh sensor data at ~50 Hz.
                    wiiDevice.SetReportType(InputReport.IRAccel, true);
                    wiiDevice.SetLEDs(true, false, false, false);

                    // Enable processing of updates.

                    infoUpdateTimer.Enabled = true;
                    // A 10 ms request produces about 60-64 Hz on Windows in
                    // practice because timer scheduling is coarser than the
                    // requested interval. Mouse-input injection was the UI
                    // interference source, so keep the validated data rate.
                    telemetrySendTimer.Change(0, 10);

                    // Prevent connect being pressed more than once.

                    button_Connect.Enabled = false;
                    button_BluetoothAddDevice.Enabled = false;
                    zeroout.Enabled = true;

                    if (checkBox_AutoTare.Checked)
                        zeroout.PerformClick();

                    break;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void wiiDevice_WiimoteChanged(object sender, WiimoteChangedEventArgs e)
        {
            // Called every time there is a sensor update, values available using e.WiimoteState.
            // Use this for tracking and filtering rapid accelerometer and gyroscope sensor data.
            // The balance board values are basic, so can be accessed directly only when needed.
            if (e.WiimoteState.ExtensionType == ExtensionType.BalanceBoard)
                UpdateTelemetrySnapshot(e.WiimoteState.BalanceBoardState);
            // Count actual HID reports to distinguish hardware/BT frequency
            // from the UI timer frequency used by InfoUpdate.
            Interlocked.Increment(ref wiimoteEventCount);
            long nowTicks = DateTime.UtcNow.Ticks;
            long startTicks = Interlocked.Read(ref wiimoteEventWindowStart);
            if (nowTicks - startTicks >= TimeSpan.TicksPerSecond &&
                Interlocked.CompareExchange(ref wiimoteEventWindowStart, nowTicks, startTicks) == startTicks)
            {
                long events = Interlocked.Exchange(ref wiimoteEventCount, 0);
                double seconds = (nowTicks - startTicks) / (double)TimeSpan.TicksPerSecond;
                string diagnostic = string.Format(
                    System.Globalization.CultureInfo.InvariantCulture,
                    "[WII-DIAG] HID report rate: {0:0.0} Hz", events / seconds);
                try
                {
                    if (!IsDisposed && IsHandleCreated)
                        BeginInvoke(new Action(() => consoleBoxWriteLine(diagnostic)));
                }
                catch (InvalidOperationException) { }
            }
        }

        private void wiiDevice_WiimoteExtensionChanged(object sender, WiimoteExtensionChangedEventArgs e)
        {
            // This is not needed for balance boards.
        }

        void infoUpdateTimer_Tick(object sender, EventArgs e)
        {
            InfoUpdate();
        }

        private void InfoUpdate()
        {
            if (wiiDevice.WiimoteState.ExtensionType != ExtensionType.BalanceBoard)
            {
                label_Status.Text = "DEVICE IS NOT A BALANCE BOARD...";
                bool hadValidControl = lastControlBoardValid;
                if (hadValidControl)
                {
                    lastControlBoardValid = false;
                }
                PublishInvalidControlSnapshot("disconnected", hadValidControl);
                return;
            }
            lastControlBoardValid = true;

            // Get the current sensor KG values. (no temperature / latitude correction, can't set zero point properly.)

            var rwWeight      = wiiDevice.WiimoteState.BalanceBoardState.WeightKg;

            var rwTopLeft     = wiiDevice.WiimoteState.BalanceBoardState.SensorValuesKg.TopLeft;
            var rwTopRight    = wiiDevice.WiimoteState.BalanceBoardState.SensorValuesKg.TopRight;
            var rwBottomLeft  = wiiDevice.WiimoteState.BalanceBoardState.SensorValuesKg.BottomLeft;
            var rwBottomRight = wiiDevice.WiimoteState.BalanceBoardState.SensorValuesKg.BottomRight;
            var aButton       = wiiDevice.WiimoteState.ButtonState.A;

            var rawTopLeft = rwTopLeft;
            var rawTopRight = rwTopRight;
            var rawBottomLeft = rwBottomLeft;
            var rawBottomRight = rwBottomRight;

            // The alternative .SensorValuesRaw is meaningless in terms of actual weight. not adjusted with 0KG, 17KG and 34KG calibration data.
            
            //var rwTopLeft     = wiiDevice.WiimoteState.BalanceBoardState.SensorValuesRaw.TopLeft     - wiiDevice.WiimoteState.BalanceBoardState.CalibrationInfo.Kg0.TopLeft;
            //var rwTopRight    = wiiDevice.WiimoteState.BalanceBoardState.SensorValuesRaw.TopRight    - wiiDevice.WiimoteState.BalanceBoardState.CalibrationInfo.Kg0.TopRight;
            //var rwBottomLeft  = wiiDevice.WiimoteState.BalanceBoardState.SensorValuesRaw.BottomLeft  - wiiDevice.WiimoteState.BalanceBoardState.CalibrationInfo.Kg0.BottomLeft;
            //var rwBottomRight = wiiDevice.WiimoteState.BalanceBoardState.SensorValuesRaw.BottomRight - wiiDevice.WiimoteState.BalanceBoardState.CalibrationInfo.Kg0.BottomRight;

            // Show the sensor values in kg.
            label_rwWT.Text = rwWeight.ToString("0.0");
            label_rwTL.Text = rwTopLeft.ToString("0.0");
            label_rwTR.Text = rwTopRight.ToString("0.0");
            label_rwBL.Text = rwBottomLeft.ToString("0.0");
            label_rwBR.Text = rwBottomRight.ToString("0.0");

            // Prevent negative values by tracking lowest possible value and making it a zero based offset.

            if (rwWeight > 5)
            {
                button_SetCenterOffset.Enabled = true;
                button_SetCenterOffset.Text = "Set current balance as center";
                //toolTip1.SetToolTip(button_SetCenterOffset, "While standing or sitting on the balance board, click this button to set your current balance point as center");
            }
            else
            {
                if (resetCenterOffsetPossible)
                {
                    button_SetCenterOffset.Enabled = true;
                    button_SetCenterOffset.Text = "Reset Center Offset";
                    //toolTip1.SetToolTip(button_SetCenterOffset, "Revert back to the original center balance point, for the X/Y controlsl");
                }

                else
                {
                    button_SetCenterOffset.Text = "Set current balance as center";
                    button_SetCenterOffset.Enabled = false;
                }
            }

            if (rwTopLeft     < naCorners) naCorners = rwTopLeft;
            if (rwTopRight    < naCorners) naCorners = rwTopRight;
            if (rwBottomLeft  < naCorners) naCorners = rwBottomLeft;
            if (rwBottomRight < naCorners) naCorners = rwBottomRight;

            // Negative total weight is reset to zero as jumping or lifting the board causes negative spikes, which would break 'in use' checks.

            var owWeight      = rwWeight < 0f ? 0f : rwWeight;

            var owTopLeft     = rwTopLeft     -= naCorners;
            var owTopRight    = rwTopRight    -= naCorners;
            var owBottomLeft  = rwBottomLeft  -= naCorners;
            var owBottomRight = rwBottomRight -= naCorners;

            // Get offset that would make current values the center of mass.

            if (setCenterOffset)
            {
                setCenterOffset = false;
                resetCenterOffsetPossible = true;
                centerGeneration++;

                var rwHighest = Math.Max(Math.Max(rwTopLeft, rwTopRight), Math.Max(rwBottomLeft, rwBottomRight));

                oaTopLeft     = rwHighest - rwTopLeft;
                oaTopRight    = rwHighest - rwTopRight;
                oaBottomLeft  = rwHighest - rwBottomLeft;
                oaBottomRight = rwHighest - rwBottomRight;
            }

            // Keep values only when board is being used, otherwise offsets and small value jitters can trigger unwanted actions.

            if (owWeight > 5f)  // minimal weight of 5kg
            {
                owTopLeft     += oaTopLeft;
                owTopRight    += oaTopRight;
                owBottomLeft  += oaBottomLeft;
                owBottomRight += oaBottomRight;
            }
            else
            {
                owTopLeft     = 0;
                owTopRight    = 0;
                owBottomLeft  = 0;
                owBottomRight = 0;
            }
            
            label_owWT.Text = owWeight.ToString("0.0");
            label_owTL.Text = owTopLeft.ToString("0.0")     + "\r\n" + oaTopLeft.ToString("0.0");
            label_owTR.Text = owTopRight.ToString("0.0")    + "\r\n" + oaTopRight.ToString("0.0");
            label_owBL.Text = owBottomLeft.ToString("0.0")  + "\r\n" + oaBottomLeft.ToString("0.0");
            label_owBR.Text = owBottomRight.ToString("0.0") + "\r\n" + oaBottomRight.ToString("0.0");

            // Calculate each weight ratio. When the board is unloaded, the
            // denominator is zero; report 0 instead of NaN.
            var totalOffsetWeight = owTopLeft + owTopRight + owBottomLeft + owBottomRight;
            var owrPercentage  = totalOffsetWeight > 0.001f ? 100 / totalOffsetWeight : 0;
            var owrTopLeft     = owrPercentage * owTopLeft;
            var owrTopRight    = owrPercentage * owTopRight;
            var owrBottomLeft  = owrPercentage * owBottomLeft;
            var owrBottomRight = owrPercentage * owBottomRight;

            label_owrTL.Text = owrTopLeft.ToString("0.0");
            label_owrTR.Text = owrTopRight.ToString("0.0");
            label_owrBL.Text = owrBottomLeft.ToString("0.0");
            label_owrBR.Text = owrBottomRight.ToString("0.0");

            // Calculate balance ratio.

            var brX = owrBottomRight + owrTopRight;
            var brY = owrBottomRight + owrBottomLeft;

            label_brX.Text = brX.ToString("0.0");
            label_brY.Text = brY.ToString("0.0");

            // Diagonal ratio used for turning on the spot.

            var brDL = owrPercentage * (owBottomLeft + owTopRight);
            var brDR = owrPercentage * (owBottomRight + owTopLeft);
            var brDF = Math.Abs(brDL - brDR);

            label_brDL.Text = brDL.ToString("0.0");
            label_brDR.Text = brDR.ToString("0.0");
            label_brDF.Text = brDF.ToString("0.0");

            // Convert sensor values into actions.

            var sendLeft          = false;
            var sendRight         = false;
            var sendForward       = false;
            var sendBackward      = false;
            var sendModifier      = false;
            var sendJump          = false;
            var sendDiagonalLeft  = false;
            var sendDiagonalRight = false;

            if (brX < (float)(50 - numericUpDown_TLR.Value)) sendLeft     = true;
            if (brX > (float)(50 + numericUpDown_TLR.Value)) sendRight    = true;
            if (brY < (float)(50 - numericUpDown_TFB.Value)) sendForward  = true;
            if (brY > (float)(50 + numericUpDown_TFB.Value)) sendBackward = true;

            if      (brX < (float)(50 - numericUpDown_TMLR.Value)) sendModifier = true;
            else if (brX > (float)(50 + numericUpDown_TMLR.Value)) sendModifier = true;
            else if (brY < (float)(50 - numericUpDown_TMFB.Value)) sendModifier = true;
            else if (brY > (float)(50 + numericUpDown_TMFB.Value)) sendModifier = true;

            // Detect jump but use a time limit to stop it being active while off the board.

            if (owWeight < 1f)
            {
                if (DateTime.UtcNow.Subtract(jumpTime).Seconds < 2) sendJump = true;
            }
            else
            {
                jumpTime = DateTime.UtcNow;
            }

            // Check for diagonal pressure only when no other movement actions are active.

            if (!sendLeft && !sendRight && !sendForward && !sendBackward && brDF > 15)
            {
                if (brDL > brDR) sendDiagonalLeft  = true;
                else             sendDiagonalRight = true;
            }

            // Display actions.

            label_Status.Text = "Result: ";

            if (sendForward)       label_Status.Text += "Forward";
            if (sendLeft)          label_Status.Text += "Left";
            if (sendBackward)      label_Status.Text += "Backward";
            if (sendRight)         label_Status.Text += "Right";
            if (sendModifier)      label_Status.Text += " + Modifier";
            if (sendJump)          label_Status.Text += "Jump";
            if (sendDiagonalLeft)  label_Status.Text += "Diagonal Left";
            if (sendDiagonalRight) label_Status.Text += "Diagonal Right";

            if (checkBox_DisableActions.Checked) label_Status.Text += " ( DISABLED )";

            // Send actions.

            if (!checkBox_DisableActions.Checked)
            {
                if (sendLeft)          actionList.Left.Start();          else actionList.Left.Stop();
                if (sendRight)         actionList.Right.Start();         else actionList.Right.Stop();
                if (sendForward)       actionList.Forward.Start();       else actionList.Forward.Stop();
                if (sendBackward)      actionList.Backward.Start();      else actionList.Backward.Stop();
                if (sendModifier)      actionList.Modifier.Start();      else actionList.Modifier.Stop();
                if (sendJump)          actionList.Jump.Start();          else actionList.Jump.Stop();
                if (sendDiagonalLeft)  actionList.DiagonalLeft.Start();  else actionList.DiagonalLeft.Stop();
                if (sendDiagonalRight) actionList.DiagonalRight.Start(); else actionList.DiagonalRight.Stop();
            }
            // When actions are disabled there is nothing to do here. Inputs
            // are released once in checkBox_DisableActions_CheckedChanged;
            // injecting key/mouse-up messages on every 20 ms UI tick can
            // interfere with the user's real mouse and makes the UI sluggish.

            // Update joystick emulator.

            if (checkBox_EnableJoystick.Checked)
            {
                double joyX = 0, joyY = 0; 

                // send X/Y position of the player's Center of Gravity through vJoy

                if (checkBox_SendCGtoXY.Checked)
                {
                    //var cgF = wiiDevice.WiimoteState.BalanceBoardState.CenterOfGravity; // this is a nice function, but since I found out that wiimote library won't let me: 1.tare the balance board 2.compensate for temperature / latitude 3.has a bug with the kg values (each sensor is 4 times too big, but the overall weight is fine) then I'm not using it. It cannot give calibrated results.

                    // Uses Int16 ( -32767 to +32767 ) where 0 is the center. Multiplied by 2 because realistic usage is between the 30-70% ratio.

                    joyX = (brX * 655.34 + -32767.0) * 2.0;
                    joyY = (brY * 655.34 + -32767.0) * 2.0;
                    //Console.WriteLine("joyX {0} JoyY {1}",joyX, joyY);

                    // Limit values to Int16, you cannot just (cast) or Convert.ToIn16() as the value '+ - sign' may invert.

                    if (joyX < short.MinValue) joyX = short.MinValue;
                    if (joyY < short.MinValue) joyY = short.MinValue;

                    if (joyX > short.MaxValue) joyX = short.MaxValue;
                    if (joyY > short.MaxValue) joyY = short.MaxValue;

                    if (Double.IsNaN(joyX)) joyX = 0.0;         // send the dead center value if not enough weight is on the board
                    if (Double.IsNaN(joyY)) joyY = 0.0;
                }
                
                if (!checkBox_Send4LoadSensors.Checked)                
                {
                    rwTopLeft = 0; rwTopRight = 0; rwBottomLeft = 0; rwBottomRight = 0;
                }
                string values = string.Format("X:{0,6:#####}  Y:{1,6:#####}  Z:{2,6:###.##}  XR:{3,6:###.##}  YR:{4,6:###.##}  ZR:{5,6:###.##}", joyX, joyY, rwTopLeft, rwTopRight, rwBottomLeft, rwBottomRight);
                
                if (checkBox_ShowValuesInConsole.Checked)
                {
                    BalanceWalker.FormMain.consoleBoxWriteLine(values);
                }
                VJoyFeeder.Setjoystick((int)joyX, (int)joyY, (int)(rwTopLeft * 100), (int)(rwTopRight * 100), (int)(rwBottomLeft * 100), (int)(rwBottomRight * 100), aButton);
            }

            PublishControlSnapshot(
                sendLeft, sendRight, sendForward, sendBackward,
                brX, brY, owWeight > 5f, "control");
        }

        private void checkBox_EnableJoystick_CheckedChanged(object sender, EventArgs e)
        {
            var isChecked = ((CheckBox)sender).Checked;
            Properties.Settings.Default.EnableJoystick = isChecked;
            Properties.Settings.Default.Save();

            bool status;
            if (checkBox_EnableJoystick.Checked)
            {
                VJoyFeeder.Initialize((uint)VJoyIDUpDown.Value);
                status = true;
            }
            else
            { 
                status = false;
            }
            checkBox_SendCGtoXY.Enabled = status;
            checkBox_Send4LoadSensors.Enabled = status;
        }

        private void FormMain_FormClosing(object sender, FormClosingEventArgs e)
        {
            // Stop updates.

            infoUpdateTimer.Enabled = false;
            telemetrySendTimer.Change(Timeout.Infinite, Timeout.Infinite);
            wiiDevice.Disconnect();

            // Prevent 'stuck' down keys from closing while doing an action.

            StopAllActions();
            telemetrySendTimer.Dispose();
            telemetryClient.Close();
        }

        private void StopAllActions()
        {
            actionList.Left.ForceStop();
            actionList.Right.ForceStop();
            actionList.Forward.ForceStop();
            actionList.Backward.ForceStop();
            actionList.Modifier.ForceStop();
            actionList.Jump.ForceStop();
            actionList.DiagonalLeft.ForceStop();
            actionList.DiagonalRight.ForceStop();

            if (!IsDisposed && !Disposing)
                PublishInvalidControlSnapshot(checkBox_DisableActions != null && checkBox_DisableActions.Checked ? "actions_disabled" : "actions_stopped", true);

        }

        private void SendTelemetry(
            double rawTL, double rawTR, double rawBL, double rawBR,
            double offsetTL, double offsetTR, double offsetBL, double offsetBR,
            double ratioTL, double ratioTR, double ratioBL, double ratioBR,
            double totalWeight)
        {
            try
            {
                // Keep the packet dependency-free so the Python receiver can
                // consume it with json.loads immediately.
                ControlTelemetrySnapshot control;
                lock (controlSnapshotLock) control = latestControlSnapshot;
                string packet = "{\"type\":\"wii_balance\",\"timestamp\":\"" +
                    DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture) +
                    "\",\"sequence\":" + (++telemetrySequence) +
                    ",\"tl\":" + FormatTelemetryValue(rawTL) +
                    ",\"tr\":" + FormatTelemetryValue(rawTR) +
                    ",\"bl\":" + FormatTelemetryValue(rawBL) +
                    ",\"br\":" + FormatTelemetryValue(rawBR) +
                    ",\"weight\":" + FormatTelemetryValue(totalWeight) +
                    ",\"offset_tl\":" + FormatTelemetryValue(offsetTL) +
                    ",\"offset_tr\":" + FormatTelemetryValue(offsetTR) +
                    ",\"offset_bl\":" + FormatTelemetryValue(offsetBL) +
                    ",\"offset_br\":" + FormatTelemetryValue(offsetBR) +
                    ",\"ratio_tl\":" + FormatTelemetryValue(ratioTL) +
                    ",\"ratio_tr\":" + FormatTelemetryValue(ratioTR) +
                    ",\"ratio_bl\":" + FormatTelemetryValue(ratioBL) +
                    ",\"ratio_br\":" + FormatTelemetryValue(ratioBR);
                double? controlAgeSeconds = control.TimestampTicks == 0 ? (double?)null : Math.Max(0, controlAgeClock.ElapsedMilliseconds - control.CaptureAgeMilliseconds) / 1000.0;
                packet += SerializeControlTelemetry(control, controlInstanceId, controlAgeSeconds);

                byte[] bytes = Encoding.UTF8.GetBytes(packet);
                telemetryClient.Send(bytes, bytes.Length, telemetryEndpoint);
            }
            catch (ObjectDisposedException) { }
            catch (SocketException) { }
        }

        private static string SerializeControlTelemetry(ControlTelemetrySnapshot control, string instanceId, double? ageSeconds)
        {
            return ",\"wii_control_schema\":\"wii_control_v1\"" +
                    ",\"wii_controller_instance_id\":" + JsonString(instanceId) +
                    ",\"wii_control_sequence\":" + JsonLong(control.Sequence) +
                    ",\"wii_control_timestamp\":" + JsonString(control.TimestampTicks == 0 ? null : new DateTime(control.TimestampTicks, DateTimeKind.Utc).ToString("o", CultureInfo.InvariantCulture)) +
                    ",\"wii_control_valid\":" + JsonBool(control.Valid) +
                    ",\"wii_control_age_seconds\":" + JsonNumber(ageSeconds) +
                    ",\"wii_control_raw_cop_not_one_to_one\":true" +
                    ",\"wii_actions_enabled\":" + JsonBool(control.ActionsEnabled) +
                    ",\"wii_joystick_enabled\":" + JsonBool(control.JoystickEnabled) +
                    ",\"wii_requested_left\":" + JsonBool(control.RequestedLeft) +
                    ",\"wii_requested_right\":" + JsonBool(control.RequestedRight) +
                    ",\"wii_requested_forward\":" + JsonBool(control.RequestedForward) +
                    ",\"wii_requested_backward\":" + JsonBool(control.RequestedBackward) +
                    ",\"wii_issued_left\":" + JsonBool(control.IssuedLeft) +
                    ",\"wii_issued_right\":" + JsonBool(control.IssuedRight) +
                    ",\"wii_issued_forward\":" + JsonBool(control.IssuedForward) +
                    ",\"wii_issued_backward\":" + JsonBool(control.IssuedBackward) +
                    ",\"wii_key_left\":" + JsonString(control.KeyLeft) +
                    ",\"wii_key_right\":" + JsonString(control.KeyRight) +
                    ",\"wii_key_forward\":" + JsonString(control.KeyForward) +
                    ",\"wii_key_backward\":" + JsonString(control.KeyBackward) +
                    ",\"wii_control_balance_x\":" + JsonNumber(control.BalanceX) +
                    ",\"wii_control_balance_y\":" + JsonNumber(control.BalanceY) +
                    ",\"wii_trigger_lr\":" + JsonNumber(control.TriggerLr) +
                    ",\"wii_trigger_fb\":" + JsonNumber(control.TriggerFb) +
                    ",\"wii_center_generation\":" + JsonLong(control.CenterGeneration) +
                    ",\"wii_center_applied\":" + JsonBool(control.CenterApplied) +
                    ",\"wii_board_loaded\":" + JsonBool(control.BoardLoaded) +
                    ",\"wii_center_offset_tl\":" + JsonNumber(control.OffsetTl) +
                    ",\"wii_center_offset_tr\":" + JsonNumber(control.OffsetTr) +
                    ",\"wii_center_offset_bl\":" + JsonNumber(control.OffsetBl) +
                    ",\"wii_center_offset_br\":" + JsonNumber(control.OffsetBr) +
                    ",\"wii_corner_floor\":" + JsonNumber(control.CornerFloor) +
                    ",\"wii_control_event\":" + JsonString(control.Event) + "}";
        }

        private void UpdateTelemetrySnapshot(BalanceBoardState board)
        {
            lock (telemetryLock)
            {
                latestRawTL = board.SensorValuesKg.TopLeft;
                latestRawTR = board.SensorValuesKg.TopRight;
                latestRawBL = board.SensorValuesKg.BottomLeft;
                latestRawBR = board.SensorValuesKg.BottomRight;
                hasTelemetrySnapshot = true;
            }
        }

        private void TelemetryTimerCallback(object state)
        {
            double rawTL, rawTR, rawBL, rawBR;
            lock (telemetryLock)
            {
                if (!hasTelemetrySnapshot) return;
                rawTL = latestRawTL;
                rawTR = latestRawTR;
                rawBL = latestRawBL;
                rawBR = latestRawBR;
            }

            double offsetTL = Math.Max(0.0, rawTL);
            double offsetTR = Math.Max(0.0, rawTR);
            double offsetBL = Math.Max(0.0, rawBL);
            double offsetBR = Math.Max(0.0, rawBR);
            double total = offsetTL + offsetTR + offsetBL + offsetBR;
            double ratioTL = total > 0.001 ? offsetTL * 100.0 / total : 0.0;
            double ratioTR = total > 0.001 ? offsetTR * 100.0 / total : 0.0;
            double ratioBL = total > 0.001 ? offsetBL * 100.0 / total : 0.0;
            double ratioBR = total > 0.001 ? offsetBR * 100.0 / total : 0.0;

            SendTelemetry(rawTL, rawTR, rawBL, rawBR,
                offsetTL, offsetTR, offsetBL, offsetBR,
                ratioTL, ratioTR, ratioBL, ratioBR, total);
        }

        private static string FormatTelemetryValue(double value)
        {
            return value.ToString("0.###", CultureInfo.InvariantCulture);
        }

        private void PublishInvalidControlSnapshot(string eventName, bool knownBoundary = false)
        {
            var snapshot = new ControlTelemetrySnapshot { Valid = false, Sequence = ++controlSequence,
                TimestampTicks = DateTime.UtcNow.Ticks, CaptureAgeMilliseconds = controlAgeClock.ElapsedMilliseconds,
                Event = eventName };
            snapshot.IssuedLeft = ReadIssued(actionList.Left);
            snapshot.IssuedRight = ReadIssued(actionList.Right);
            snapshot.IssuedForward = ReadIssued(actionList.Forward);
            snapshot.IssuedBackward = ReadIssued(actionList.Backward);
            snapshot.KeyLeft = ReadKeyName(actionList.Left); snapshot.KeyRight = ReadKeyName(actionList.Right);
            snapshot.KeyForward = ReadKeyName(actionList.Forward); snapshot.KeyBackward = ReadKeyName(actionList.Backward);
            if (knownBoundary)
            {
                snapshot.ActionsEnabled = ReadChecked(checkBox_DisableActions, true);
                snapshot.JoystickEnabled = ReadChecked(checkBox_EnableJoystick, false);
                snapshot.CenterGeneration = centerGeneration;
                snapshot.CenterApplied = false;
                snapshot.OffsetTl = oaTopLeft; snapshot.OffsetTr = oaTopRight;
                snapshot.OffsetBl = oaBottomLeft; snapshot.OffsetBr = oaBottomRight;
                snapshot.CornerFloor = naCorners;
            }
            lock (controlSnapshotLock) latestControlSnapshot = snapshot;
        }

        private void PublishControlSnapshot(bool left, bool right, bool forward, bool backward,
            double balanceX, double balanceY, bool boardLoaded, string eventName)
        {
            var actionsEnabled = !checkBox_DisableActions.Checked;
            var snapshot = new ControlTelemetrySnapshot {
                Valid = true, Sequence = ++controlSequence, TimestampTicks = DateTime.UtcNow.Ticks,
                CaptureAgeMilliseconds = controlAgeClock.ElapsedMilliseconds,
                ActionsEnabled = actionsEnabled, JoystickEnabled = checkBox_EnableJoystick.Checked,
                RequestedLeft = left, RequestedRight = right, RequestedForward = forward, RequestedBackward = backward,
                IssuedLeft = ReadIssued(actionList.Left), IssuedRight = ReadIssued(actionList.Right),
                IssuedForward = ReadIssued(actionList.Forward), IssuedBackward = ReadIssued(actionList.Backward),
                KeyLeft = ReadKeyName(actionList.Left), KeyRight = ReadKeyName(actionList.Right),
                KeyForward = ReadKeyName(actionList.Forward), KeyBackward = ReadKeyName(actionList.Backward),
                BalanceX = balanceX, BalanceY = balanceY,
                TriggerLr = (double)numericUpDown_TLR.Value, TriggerFb = (double)numericUpDown_TFB.Value,
                CenterGeneration = centerGeneration, CenterApplied = boardLoaded && resetCenterOffsetPossible, BoardLoaded = boardLoaded,
                OffsetTl = oaTopLeft, OffsetTr = oaTopRight, OffsetBl = oaBottomLeft, OffsetBr = oaBottomRight,
                CornerFloor = naCorners, Event = checkBox_DisableActions == null ? eventName : (checkBox_DisableActions.Checked ? "actions_disabled" : eventName)
            };
            lock (controlSnapshotLock) latestControlSnapshot = snapshot;
        }

        private static string JsonBool(bool? value) { return value.HasValue ? (value.Value ? "true" : "false") : "null"; }
        private static string JsonLong(long? value) { return value.HasValue ? value.Value.ToString(CultureInfo.InvariantCulture) : "null"; }
        private static bool? ReadIssued(ActionItem item) { return item == null ? (bool?)null : item.IsActive && item.IsKeyboardAction; }
        private static string ReadKeyName(ActionItem item) { return item == null ? null : item.KeyName; }
        private bool? ReadChecked(CheckBox control, bool invert)
        {
            if (control == null || IsDisposed || Disposing || control.IsDisposed) return null;
            return invert ? !control.Checked : control.Checked;
        }
        private static string JsonNumber(double? value) { return value.HasValue && !double.IsNaN(value.Value) && !double.IsInfinity(value.Value) ? FormatTelemetryValue(value.Value) : "null"; }
        private static string JsonString(string value)
        {
            if (value == null) return "null";
            var escaped = new StringBuilder(value.Length + 2);
            escaped.Append('"');
            foreach (char character in value)
            {
                switch (character)
                {
                    case '\\': escaped.Append("\\\\"); break;
                    case '"': escaped.Append("\\\""); break;
                    case '\b': escaped.Append("\\b"); break;
                    case '\f': escaped.Append("\\f"); break;
                    case '\n': escaped.Append("\\n"); break;
                    case '\r': escaped.Append("\\r"); break;
                    case '\t': escaped.Append("\\t"); break;
                    default:
                        if (character < 0x20) escaped.Append("\\u").Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                        else escaped.Append(character);
                        break;
                }
            }
            escaped.Append('"');
            return escaped.ToString();
        }

        private void zeroout_Click(object sender, EventArgs e)
        {
            wiiDevice.WiimoteState.BalanceBoardState.ZeroPoint.Reset = true;
            naCorners = 0f;
            oaTopLeft = 0f;
            oaTopRight = 0f;
            oaBottomLeft = 0f;
            oaBottomRight = 0f;
            centerGeneration++;
            PublishInvalidControlSnapshot("zeroout", true);
        }

        public void consoleBoxWriteLine(string line)
        {
            consoleBox.AppendText(line);
            consoleBox.AppendText(Environment.NewLine);
        }

        private void checkBox_DisableActions_CheckedChanged(object sender, EventArgs e)
        {
            var isChecked = ((CheckBox)sender).Checked;
            Properties.Settings.Default.DisableActions = isChecked;
            Properties.Settings.Default.Save();

            if (isChecked)
                StopAllActions();

            bool status;
            if (checkBox_DisableActions.Checked)
                status = false;
            else
                status = true;

            label_ActionLeft.Enabled = status;
            label_ActionRight.Enabled = status;
            label_ActionForward.Enabled = status;
            label_ActionBackward.Enabled = status;
            label_ActionModifier.Enabled = status;
            label_ActionJump.Enabled = status;
            label_ActionDiagonalLeft.Enabled = status;
            label_ActionDiagonalRight.Enabled = status;
            label_TLR.Enabled = status;
            label_TFB.Enabled = status;
            label_TMLR.Enabled = status;
            label_TMFB.Enabled = status;
        }

        private void ShowValues_CheckedChanged(object sender, EventArgs e)
        {
            var isChecked = ((CheckBox)sender).Checked;
            Properties.Settings.Default.ShowValuesInConsole = isChecked;
            Properties.Settings.Default.Save();
        }

        private void checkBox_SendCGtoXY_CheckedChanged(object sender, EventArgs e)
        {
            var isChecked = ((CheckBox)sender).Checked;
            Properties.Settings.Default.SendCGtoXY = isChecked;
            Properties.Settings.Default.Save();
        }

        private void checkBox_Send4LoadSensors_CheckedChanged(object sender, EventArgs e)
        {
            var isChecked = ((CheckBox)sender).Checked;
            Properties.Settings.Default.Send4LoadSensors = isChecked;
            Properties.Settings.Default.Save();
        }

        private void checkBox_StartupAutoConnect_CheckedChanged(object sender, EventArgs e)
        {
            var isChecked = ((CheckBox)sender).Checked;
            Properties.Settings.Default.StartupAutoConnect = isChecked;
            Properties.Settings.Default.Save();
        }

        private void checkBox_AutoTare_CheckedChanged(object sender, EventArgs e)
        {
            var isChecked = ((CheckBox)sender).Checked;
            Properties.Settings.Default.AutoTare = isChecked;
            Properties.Settings.Default.Save();
        }

        private void checkBox_StartMinimized_CheckedChanged(object sender, EventArgs e)
        {
            var isChecked = ((CheckBox)sender).Checked;
            Properties.Settings.Default.StartMinimized = isChecked;
            Properties.Settings.Default.Save();
        }
    }
}
