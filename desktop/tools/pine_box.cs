// pine_box.exe — run Pine Box Desktop from ANY PC on the network.
//
// What it does, in order:
//   1. finds the stack share (default \\10.89.1.246\ehm_eckx\pinevoice-stack,
//      override with env PINE_STACK);
//   2. mirrors spark-agent\desktop + package.json into a local runner at
//      %LOCALAPPDATA%\PineBoxDesktop\runner (SMB is too slow to run from);
//   3. if the local Electron runtime is missing, extracts
//      desktop-runtime\electron-win64.zip off the share — no Node, no npm,
//      no internet needed on the PC;
//   4. sets the session env (agent URL, agent root, attach mode; clears
//      the ELECTRON_RUN_AS_NODE trap) and launches electron.exe.
//
// Build (any Windows box, no SDK needed):
//   %WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo
//     /r:System.IO.Compression.FileSystem.dll /r:System.IO.Compression.dll
//     /out:pine_box.exe pine_box.cs
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;

static class PineBox
{
    const string DefaultStack = @"\\10.89.1.246\ehm_eckx\pinevoice-stack";
    const string BaseUrl = "http://10.89.1.246:8096";

    static void Say(string line)
    {
        Console.WriteLine("[pinebox] " + line);
    }

    static int Fail(string why)
    {
        Say("FAILED: " + why);
        Console.WriteLine();
        Console.WriteLine("Press any key to close…");
        try { Console.ReadKey(true); } catch (Exception) { }
        return 1;
    }

    // Mirror one directory (delete-extra like robocopy /MIR, but tiny).
    static void Mirror(string from, string to)
    {
        Directory.CreateDirectory(to);
        foreach (string dir in Directory.GetDirectories(from, "*",
                 SearchOption.AllDirectories))
        {
            Directory.CreateDirectory(to + dir.Substring(from.Length));
        }
        foreach (string file in Directory.GetFiles(from, "*",
                 SearchOption.AllDirectories))
        {
            string dest = to + file.Substring(from.Length);
            FileInfo src = new FileInfo(file);
            FileInfo dst = new FileInfo(dest);
            if (!dst.Exists || dst.Length != src.Length
                || dst.LastWriteTimeUtc < src.LastWriteTimeUtc)
            {
                File.Copy(file, dest, true);
            }
        }
        foreach (string file in Directory.GetFiles(to, "*",
                 SearchOption.AllDirectories))
        {
            if (!File.Exists(from + file.Substring(to.Length)))
            {
                try { File.Delete(file); } catch (Exception) { }
            }
        }
    }

    static int Main()
    {
        string stack = Environment.GetEnvironmentVariable("PINE_STACK");
        if (string.IsNullOrEmpty(stack)) stack = DefaultStack;
        string agent = Path.Combine(stack, "spark-agent");
        string runDir = Environment.GetEnvironmentVariable("PINE_RUN_DIR");
        if (string.IsNullOrEmpty(runDir))
        {
            runDir = Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
                @"PineBoxDesktop\runner");
        }

        Say("stack:  " + stack);
        Say("runner: " + runDir);
        if (!File.Exists(Path.Combine(agent, "package.json")))
        {
            return Fail("cannot reach " + agent + "\r\n  Is this PC on "
                + "TacoNet, and is the share reachable? (override with "
                + "env PINE_STACK)");
        }

        try
        {
            Say("mirroring the desktop app to the local runner…");
            Directory.CreateDirectory(runDir);
            File.Copy(Path.Combine(agent, "package.json"),
                      Path.Combine(runDir, "package.json"), true);
            string lockFile = Path.Combine(agent, "package-lock.json");
            if (File.Exists(lockFile))
            {
                File.Copy(lockFile,
                          Path.Combine(runDir, "package-lock.json"), true);
            }
            Mirror(Path.Combine(agent, "desktop"),
                   Path.Combine(runDir, "desktop"));
        }
        catch (Exception exc)
        {
            return Fail("could not copy the app: " + exc.Message);
        }

        string electron = Path.Combine(runDir,
            @"node_modules\electron\dist\electron.exe");
        if (!File.Exists(electron))
        {
            string zip = Path.Combine(stack,
                @"desktop-runtime\electron-win64.zip");
            if (!File.Exists(zip))
            {
                return Fail("no local Electron and no runtime bundle at\r\n  "
                    + zip);
            }
            Say("first run on this PC — unpacking the Electron runtime "
                + "(~300 MB, one time)…");
            string dest = Path.Combine(runDir, @"node_modules\electron");
            try
            {
                if (Directory.Exists(dest)) Directory.Delete(dest, true);
                Directory.CreateDirectory(dest);
                ZipFile.ExtractToDirectory(zip, dest);
            }
            catch (Exception exc)
            {
                return Fail("could not unpack the runtime: " + exc.Message);
            }
        }
        if (!File.Exists(electron))
        {
            return Fail("electron.exe still missing after unpack");
        }
        // The runtime marker electron's index.js insists on.
        try
        {
            File.WriteAllText(Path.Combine(runDir,
                @"node_modules\electron\path.txt"), "electron.exe");
        }
        catch (Exception) { }

        Say("launching Pine Box Desktop → " + BaseUrl);
        ProcessStartInfo psi = new ProcessStartInfo(electron, ".");
        psi.WorkingDirectory = runDir;
        psi.UseShellExecute = false;
        psi.EnvironmentVariables["PINE_AGENT_ROOT"] = agent;
        psi.EnvironmentVariables["PINE_DESKTOP_BASE_URL"] = BaseUrl;
        psi.EnvironmentVariables["PINE_DESKTOP_MODE"] = "attach";
        // Shells spawned from VS Code / Electron apps inherit this and it
        // turns electron.exe into plain Node. Always clear it.
        psi.EnvironmentVariables.Remove("ELECTRON_RUN_AS_NODE");

        if (Environment.GetEnvironmentVariable("PINE_DRY") == "1")
        {
            Say("PINE_DRY=1 — everything is staged; skipping the launch.");
            return 0;
        }
        try
        {
            Process.Start(psi);
        }
        catch (Exception exc)
        {
            return Fail("electron would not start: " + exc.Message);
        }
        Say("up. This window can be closed.");
        return 0;
    }
}
