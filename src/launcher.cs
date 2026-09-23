using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Orvo")]
[assembly: AssemblyProduct("Orvo")]
[assembly: AssemblyDescription("Orvo - Voice Dictation Everywhere")]
[assembly: AssemblyCompany("Orvo")]
[assembly: AssemblyCopyright("Copyright © 2026")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace OrvoLauncher {
    static class Program {
        [STAThread]
        static void Main(string[] args) {
            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            string venvPythonW = Path.Combine(appDir, ".venv", "Scripts", "pythonw.exe");
            string venvPython = Path.Combine(appDir, ".venv", "Scripts", "python.exe");
            string mainPy = Path.Combine(appDir, "main.py");

            if (!File.Exists(mainPy)) {
                MessageBox.Show("main.py was not found in: " + appDir, "Orvo Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            string pythonExe = File.Exists(venvPythonW) ? venvPythonW : (File.Exists(venvPython) ? venvPython : "pythonw.exe");

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonExe;
            string argList = "\"" + mainPy + "\"";
            if (args != null && args.Length > 0) {
                argList += " " + string.Join(" ", args);
            }
            psi.Arguments = argList;
            psi.WorkingDirectory = appDir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;

            try {
                using (Process proc = Process.Start(psi)) {
                    if (proc != null) {
                        proc.WaitForExit();
                    }
                }
            } catch (Exception ex) {
                MessageBox.Show("Failed to launch Orvo:\n\n" + ex.Message, "Orvo Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }
}
