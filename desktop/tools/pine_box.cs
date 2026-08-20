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
//   4. writes a Start Menu shortcut called "Pine Box" carrying the app's
//      AppUserModelID and its icon, so the thing can be pinned to the
//      taskbar and pinned correctly (#971);
//   5. sets the session env (agent URL, agent root, attach mode; clears
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
using System.Runtime.InteropServices;
using System.Text;

// #971 — the COM needed to write a shortcut that Windows will accept as
// an application's own. WScript.Shell can set a target and an icon and
// nothing else; the AppUserModelID lives in the shortcut's PROPERTY
// STORE, and only IShellLink + IPropertyStore can put it there. Without
// it the shell has no way to know that the running electron.exe window
// and the pinned shortcut are the same application, which is the whole
// fault this fixes.
[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
class CShellLink { }

[ComImport, Guid("000214F9-0000-0000-C000-000000000046"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellLinkW
{
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder f,
                 int cch, IntPtr fd, uint flags);
    void GetIDList(out IntPtr ppidl);
    void SetIDList(IntPtr pidl);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder n,
                        int cch);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string n);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder d,
                             int cch);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string d);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder a,
                      int cch);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string a);
    void GetHotkey(out short hk);
    void SetHotkey(short hk);
    void GetShowCmd(out int cmd);
    void SetShowCmd(int cmd);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder i,
                         int cch, out int idx);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string i, int idx);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pth, uint res);
    void Resolve(IntPtr hwnd, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pth);
}

[ComImport, Guid("0000010b-0000-0000-C000-000000000046"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPersistFile
{
    void GetClassID(out Guid c);
    [PreserveSig] int IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint mode);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string f,
              [MarshalAs(UnmanagedType.Bool)] bool remember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f);
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f);
}

[StructLayout(LayoutKind.Sequential)]
struct PropertyKey
{
    public Guid fmtid;
    public uint pid;
    public PropertyKey(Guid g, uint p) { fmtid = g; pid = p; }
}

[ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore
{
    void GetCount(out uint c);
    void GetAt(uint i, out PropertyKey k);
    void GetValue(ref PropertyKey k, [In, Out] PropVariant v);
    void SetValue(ref PropertyKey k, [In] PropVariant v);
    void Commit();
}

[StructLayout(LayoutKind.Explicit)]
sealed class PropVariant : IDisposable
{
    [FieldOffset(0)] ushort vt;
    [FieldOffset(8)] IntPtr ptr;

    public PropVariant() { vt = 0; }                    // VT_EMPTY
    public PropVariant(string value)
    {
        vt = 31;                                        // VT_LPWSTR
        ptr = Marshal.StringToCoTaskMemUni(value);
    }
    public void Dispose()
    {
        PropVariantClear(this);
        GC.SuppressFinalize(this);
    }
    ~PropVariant() { Dispose(); }

    [DllImport("ole32.dll", PreserveSig = false)]
    static extern void PropVariantClear([In, Out] PropVariant pvar);
}

static class PineBox
{
    const string DefaultStack = @"\\10.89.1.246\ehm_eckx\pinevoice-stack";
    const string BaseUrl = "http://10.89.1.246:8096";
    // #971: the one identity string. It MUST be character-for-character
    // the same as the PINE_AUMID that desktop\main.js hands
    // app.setAppUserModelId(), or the running window and the pinned
    // button become two separate taskbar buttons again.
    const string Aumid = "local.lilspark.pinebox";
    const string AppName = "Pine Box";

    // #971: put "Pine Box" in the Start Menu, pointing at the local
    // runner, wearing the pine mark, and carrying the AppUserModelID.
    //
    // Rewritten on every launch on purpose. The runner is re-mirrored and
    // the Electron runtime can be re-unpacked underneath it, so a
    // shortcut written once and left alone is a shortcut that eventually
    // points at something that has moved. This is cheap and self-healing.
    //
    // Never fatal: a machine with a locked-down shell still gets its app.
    static void WriteShortcut(string runDir)
    {
        string electron = Path.Combine(runDir,
            @"node_modules\electron\dist\electron.exe");
        string icon = Path.Combine(runDir,
            @"desktop\assets\pinebox.ico");
        string programs = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            @"Microsoft\Windows\Start Menu\Programs");
        string lnk = Path.Combine(programs, AppName + ".lnk");
        try
        {
            Directory.CreateDirectory(programs);
            CShellLink raw = new CShellLink();
            IShellLinkW link = (IShellLinkW)raw;
            link.SetPath(electron);
            // "." is the app directory, relative to the working directory
            // below. This is the argument the old broken pin was missing:
            // electron.exe with no argument opens a blank Electron, which
            // is exactly what the operator's pinned button did.
            link.SetArguments(".");
            link.SetWorkingDirectory(runDir);
            if (File.Exists(icon)) link.SetIconLocation(icon, 0);
            link.SetDescription("Pine Box \u2014 the station, on this PC");
            IPropertyStore store = (IPropertyStore)raw;
            PropertyKey key = new PropertyKey(
                new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
            PropVariant pv = new PropVariant(Aumid);
            try
            {
                store.SetValue(ref key, pv);
                store.Commit();
            }
            finally { pv.Dispose(); }
            ((IPersistFile)raw).Save(lnk, true);
            Marshal.FinalReleaseComObject(raw);
            Say("Start Menu entry ready — search \"Pine Box\", then "
                + "right-click it to pin.");
        }
        catch (Exception exc)
        {
            Say("could not write the Start Menu shortcut (" + exc.Message
                + ") — the app still launches.");
        }
    }

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

        // #971: the shortcut is refreshed now, after the runner and the
        // Electron runtime are both known to be in place — a shortcut
        // written before that could point at an electron.exe that the
        // unpack step was about to replace.
        WriteShortcut(runDir);

        Say("launching Pine Box → " + BaseUrl);
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
