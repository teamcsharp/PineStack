param([Parameter(Mandatory=$true)][int]$AppProcessId, [switch]$Repair)
$ErrorActionPreference = 'Stop'
try {
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;
namespace PineAudioOutput {
 [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class Enumerator {}
 [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IDevices {
  void EnumAudioEndpoints(int flow, uint state, out ICollection devices);
  void GetDefaultAudioEndpoint(int flow, int role, out IDevice device);
 }
 [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface ICollection { void GetCount(out uint count); void Item(uint index, out IDevice device); }
 [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IDevice {
  void Activate(ref Guid iid, uint context, IntPtr parameters, [MarshalAs(UnmanagedType.IUnknown)] out object value);
  void OpenPropertyStore(uint access, out IntPtr properties);
  void GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
  void GetState(out uint state);
 }
 [ComImport, Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IManager {
  void GetAudioSessionControl(IntPtr session, uint flags, out IntPtr value);
  void GetSimpleAudioVolume(IntPtr session, uint flags, out IntPtr value);
  void GetSessionEnumerator(out ISessions sessions);
 }
 [ComImport, Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface ISessions { void GetCount(out int count); void GetSession(int index, out IControl control); }
 [ComImport, Guid("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IControl {
  void GetState(out int state); void GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string name);
  void SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string name, ref Guid context);
  void GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string path); void SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string path, ref Guid context);
  void GetGroupingParam(out Guid grouping); void SetGroupingParam(ref Guid grouping, ref Guid context);
  void RegisterAudioSessionNotification(IntPtr notification); void UnregisterAudioSessionNotification(IntPtr notification);
  void GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id); void GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
  [PreserveSig] int GetProcessId(out uint process); [PreserveSig] int IsSystemSoundsSession(); void SetDuckingPreference([MarshalAs(UnmanagedType.Bool)] bool optOut);
 }
 [ComImport, Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IVolume {
  void SetMasterVolume(float volume, ref Guid context); void GetMasterVolume(out float volume);
  void SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid context); void GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
 }
 [ComImport, Guid("C02216F6-8C67-4B5B-9D00-D008E73E0064"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IMeter { void GetPeakValue(out float peak); }
 [ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IEndpointVolume {
  void RegisterControlChangeNotify(IntPtr value); void UnregisterControlChangeNotify(IntPtr value); void GetChannelCount(out uint count);
  void SetMasterVolumeLevel(float level, ref Guid context); void SetMasterVolumeLevelScalar(float level, ref Guid context);
  void GetMasterVolumeLevel(out float level); void GetMasterVolumeLevelScalar(out float level);
  void SetChannelVolumeLevel(uint channel, float level, ref Guid context); void SetChannelVolumeLevelScalar(uint channel, float level, ref Guid context);
  void GetChannelVolumeLevel(uint channel, out float level); void GetChannelVolumeLevelScalar(uint channel, out float level);
  void SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid context); void GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
 }
 public class Session { public uint process; public bool muted; public float volume; public float peak; public bool defaultOutput; }
 public class Result { public bool ok; public string say; public string defaultDevice; public bool deviceMuted; public float deviceVolume; public float peak; public List<Session> sessions = new List<Session>(); public List<string> changed = new List<string>(); }
 public static class Output {
  public static Result Read(int[] processes, bool repair) {
   var result = new Result(); var held = new List<object>(); var targets = new HashSet<int>(processes); var context = Guid.Empty;
   try {
    var devices = (IDevices)new Enumerator(); held.Add(devices); IDevice primary; devices.GetDefaultAudioEndpoint(0, 1, out primary); held.Add(primary);
    primary.GetId(out result.defaultDevice); object endpointObject; var endpointId = typeof(IEndpointVolume).GUID; primary.Activate(ref endpointId, 23, IntPtr.Zero, out endpointObject); held.Add(endpointObject);
    var endpoint = (IEndpointVolume)endpointObject; endpoint.GetMute(out result.deviceMuted); endpoint.GetMasterVolumeLevelScalar(out result.deviceVolume);
    if (repair && result.deviceMuted) { endpoint.SetMute(false, ref context); result.deviceMuted = false; result.changed.Add("Unmuted the default Windows output device."); }
    if (repair && result.deviceVolume <= 0) { endpoint.SetMasterVolumeLevelScalar(.35f, ref context); result.deviceVolume = .35f; result.changed.Add("Restored default Windows output volume to 35%."); }
    ICollection collection; devices.EnumAudioEndpoints(0, 1, out collection); held.Add(collection); uint deviceCount; collection.GetCount(out deviceCount);
    var meters = new List<KeyValuePair<Session,IMeter>>();
    for (uint d = 0; d < deviceCount; d++) {
     IDevice device; collection.Item(d, out device); held.Add(device); string id; device.GetId(out id); object managerObject; var managerId = typeof(IManager).GUID;
     try { device.Activate(ref managerId, 23, IntPtr.Zero, out managerObject); } catch { continue; }
     held.Add(managerObject); ISessions sessions; ((IManager)managerObject).GetSessionEnumerator(out sessions); held.Add(sessions); int count; sessions.GetCount(out count);
     for (int i = 0; i < count; i++) {
      IControl control; sessions.GetSession(i, out control); held.Add(control); uint process; if (control.GetProcessId(out process) < 0 || !targets.Contains((int)process)) continue;
      var volume = (IVolume)control; var session = new Session { process = process, defaultOutput = id == result.defaultDevice }; volume.GetMute(out session.muted); volume.GetMasterVolume(out session.volume);
      if (repair && session.muted) { volume.SetMute(false, ref context); session.muted = false; result.changed.Add("Unmuted Pine in the Windows volume mixer."); }
      if (repair && session.volume <= 0) { volume.SetMasterVolume(.7f, ref context); session.volume = .7f; result.changed.Add("Restored Pine's Windows mixer volume to 70%."); }
      result.sessions.Add(session); try { meters.Add(new KeyValuePair<Session,IMeter>(session, (IMeter)control)); } catch { }
     }
    }
    for (int sample = 0; sample < 10; sample++) { foreach (var meter in meters) { try { float peak; meter.Value.GetPeakValue(out peak); meter.Key.peak = Math.Max(meter.Key.peak, peak); result.peak = Math.Max(result.peak, peak); } catch { } } Thread.Sleep(100); }
    result.ok = true; result.say = result.sessions.Count == 0 ? "No Pine audio session is active in Windows yet." : result.deviceMuted || result.deviceVolume <= 0 ? "The default Windows output is muted or at zero." : "Windows output and Pine audio sessions checked.";
   } catch (Exception error) { result.say = "Windows audio check failed: " + error.Message + " Check the selected device in Windows Sound settings."; }
   finally { for (int i = held.Count - 1; i >= 0; i--) { try { Marshal.ReleaseComObject(held[i]); } catch { } } }
   return result;
  }
 }
}
'@
$audioProcesses = @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId)
$audioTargets = [System.Collections.Generic.HashSet[int]]::new()
[void]$audioTargets.Add($AppProcessId)
do {
 $audioAdded = $false
 foreach ($audioProcess in $audioProcesses) { if ($audioTargets.Contains([int]$audioProcess.ParentProcessId) -and $audioTargets.Add([int]$audioProcess.ProcessId)) { $audioAdded = $true } }
} while ($audioAdded)
[PineAudioOutput.Output]::Read([int[]]@($audioTargets), [bool]$Repair) | ConvertTo-Json -Depth 5 -Compress
} catch { @{ ok=$false; say=$_.Exception.Message; changed=@(); peak=0 } | ConvertTo-Json -Compress }
