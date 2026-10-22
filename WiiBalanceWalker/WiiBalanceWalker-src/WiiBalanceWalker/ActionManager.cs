using System;
using System.Windows.Forms;
using InputManager;

namespace WiiBalanceWalker
{
    /// <summary>Actions place holders as controls are passed after they load.</summary>
    public class ActionList
    {
        public ActionItem Left;
        public ActionItem Right;
        public ActionItem Forward;
        public ActionItem Backward;
        public ActionItem Modifier;
        public ActionItem Jump;
        public ActionItem DiagonalLeft;
        public ActionItem DiagonalRight;
    }

    /// <summary>Abstracts away selecting, saving, and sending multiple input types.</summary>
    public class ActionItem
    {
        public bool         IsActive        { get; private set; }
        public bool IsKeyboardAction { get { return inputType == 1; } }
        public string KeyName { get { return inputType == 1 ? inputKeys.ToString() : null; } }
        string              settingName;
        string              inputText;
        int                 inputAmount;
        int                 inputType;
        Keys                inputKeys;

        public ActionItem(string settingName, ComboBox controlType, NumericUpDown controlAmount)
        {
            // The name where the action should be saved.

            this.settingName = settingName;

            // Track changes to the controls.

            controlType.SelectedIndexChanged += new EventHandler(ControlType_SelectedIndexChanged);
            controlAmount.ValueChanged       += new EventHandler(ControlAmount_ValueChanged);

            // This build is used for keyboard/WASD control and telemetry.
            // Do not expose Windows mouse injection: old diagonal defaults
            // could move or release the real desktop mouse while using the
            // balance board.

            controlType.Items.Add(new ItemWithText("",           "Do Nothing"));

            // Add keyboard options to control.

            foreach (Keys item in Enum.GetValues(typeof(Keys)))
            {
                controlType.Items.Add(new ItemWithText(item, "Key " + item));
            }

            // Get the last known settings.

            inputText   = (string)Properties.Settings.Default["Action" + settingName];
            inputAmount =    (int)Properties.Settings.Default["Amount" + settingName];

            // Migrate any persisted setting created by an older build.
            if (inputText.StartsWith("Mouse ", StringComparison.OrdinalIgnoreCase))
            {
                inputText = "Do Nothing";
                Properties.Settings.Default["Action" + settingName] = inputText;
                Properties.Settings.Default.Save();
            }

            // Put the controls to the last known settings.

            controlType.Text    = inputText;
            controlAmount.Value = inputAmount;

        }

        public void ControlType_SelectedIndexChanged(object sender, EventArgs e)
        {
            // Convert control generic object back into item.

            var itemWithText = (ItemWithText)((ComboBox)sender).SelectedItem;
            var itemTypeName = itemWithText.Item.GetType().Name;

            // Set the active item.

            if (itemTypeName == "Keys")
            {
                inputKeys = (Keys)itemWithText.Item;
                inputType = 1;
            }
            else if (itemTypeName == "String")
            {
                var itemText = (String)itemWithText.Item;

                if      (itemText == "")           inputType = 0;
            }

            // Remember settings.

            inputText = ((ComboBox)sender).Text;
            Save();
        }

        public void ControlAmount_ValueChanged(object sender, EventArgs e)
        {
            // Convert control decimal to integer and remember setting.

            inputAmount = (int)((NumericUpDown)sender).Value;
            Save();
        }

        public void Start()
        {
            // Keyboard Keys and Mouse buttons need only to signal down then up to hold.
            // Mouse movement is incremental jumps so needs a faster repeating timer for smooth movement.

            if (this.IsActive) return;
            this.IsActive = true;

            switch (inputType)
            {
                case 0:
                    return;
                case 1:
                    Keyboard.KeyDown(inputKeys);
                    break;
            }
        }

        public void Stop()
        {
            if (!this.IsActive) return;
            this.IsActive = false;

            switch (inputType)
            {
                case 0:
                    return;
                case 1:
                    Keyboard.KeyUp(inputKeys);
                    break;
            }
        }

        // Releases the underlying simulated input even if the local active
        // flag was lost during a disconnect, exception, or settings change.
        // This prevents Windows from retaining a stuck Shift/Ctrl/mouse state.
        public void ForceStop()
        {
            this.IsActive = false;

            if (inputType == 1)
                Keyboard.KeyUp(inputKeys);
        }

        public void Save()
        {
            Properties.Settings.Default["Action" + settingName] = inputText;
            Properties.Settings.Default["Amount" + settingName] = inputAmount;
            Properties.Settings.Default.Save();
        }
    }

    /// <summary>Used to store objects with custom text as a control item.</summary>
    public class ItemWithText
    {
        public object Item { get; private set; }
        public string Text { get; private set; }

        public ItemWithText(object item, string text)
        {
            this.Item = item;
            this.Text = text;
        }

        public override string ToString()
        {
            return this.Text;
        }
    }
}
