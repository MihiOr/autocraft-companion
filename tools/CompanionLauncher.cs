using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class CompanionLauncher {
    [STAThread]
    static void Main() {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        string script = Path.Combine(folder, "src", "app.py");
        string python = Path.Combine(folder, ".venv", "Scripts", "pythonw.exe");
        try {
            if (!File.Exists(script)) throw new FileNotFoundException("Keep this launcher in the Companion folder with its src folder.");
            var start = new ProcessStartInfo();
            start.FileName = File.Exists(python) ? python : "pyw.exe";
            start.Arguments = (File.Exists(python) ? "" : "-3 ") + "\"" + script + "\"";
            start.WorkingDirectory = folder;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            Process.Start(start);
        } catch (Exception error) {
            MessageBox.Show(error.Message, "AutoCraft Companion", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
