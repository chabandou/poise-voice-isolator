<#
.SYNOPSIS
  List, rename and pick the default of Windows audio endpoints (CI helper).

.DESCRIPTION
  The hosted Windows runner has no sound card; CI installs VB-Cable and
  needs the endpoints laid out as on a real box. Uses the endpoint
  builder's own policy interface (what the Sound control panel calls),
  so it needs an elevated shell.

  -List                       print every render/capture endpoint
  -Rename <id-or-name>=<new>  set an endpoint's name (its device description,
                              the part before the parentheses)
  -Default <name>             make the render endpoint whose full name
                              contains <name> the default for every role
  -AddDevice <inf>            one more root device driven by <inf> (as
                              devcon install), with -HardwareId; then waits
                              up to -WaitFor seconds for an endpoint whose
                              name contains -WaitName
#>
param(
    [switch]$List,
    [string[]]$Rename = @(),
    [string]$Default,
    [string]$AddDevice,
    [string]$HardwareId,
    [string]$WaitName,
    [int]$WaitFor = 60
)
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace PoiseCi {
  [StructLayout(LayoutKind.Sequential)]
  public struct PropertyKey { public Guid fmtid; public int pid;
    public PropertyKey(string g, int p) { fmtid = new Guid(g); pid = p; } }

  [StructLayout(LayoutKind.Explicit, Size = 24)]
  public struct PropVariant {
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr ptr;
  }

  [ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPropertyStore {
    [PreserveSig] int GetCount(out int n);
    [PreserveSig] int GetAt(int i, out PropertyKey key);
    [PreserveSig] int GetValue(ref PropertyKey key, out PropVariant pv);
    [PreserveSig] int SetValue(ref PropertyKey key, ref PropVariant pv);
    [PreserveSig] int Commit();
  }

  [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice {
    [PreserveSig] int Activate(ref Guid iid, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o);
    [PreserveSig] int OpenPropertyStore(int access, out IPropertyStore store);
    [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    [PreserveSig] int GetState(out int state);
  }

  [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceCollection {
    [PreserveSig] int GetCount(out int n);
    [PreserveSig] int Item(int i, out IMMDevice dev);
  }

  [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator {
    [PreserveSig] int EnumAudioEndpoints(int flow, int mask, out IMMDeviceCollection devs);
    [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice dev);
  }

  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
  class MMDeviceEnumerator {}

  // Undocumented, stable since Vista: what mmsys.cpl uses to rename
  // endpoints and to set the default.
  [ComImport, Guid("f8679f50-850a-41cf-9c72-430f290290c8"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPolicyConfig {
    [PreserveSig] int GetMixFormat(string id, IntPtr fmt);
    [PreserveSig] int GetDeviceFormat(string id, int def, IntPtr fmt);
    [PreserveSig] int ResetDeviceFormat(string id);
    [PreserveSig] int SetDeviceFormat(string id, IntPtr fmt, IntPtr mix);
    [PreserveSig] int GetProcessingPeriod(string id, int def, IntPtr a, IntPtr b);
    [PreserveSig] int SetProcessingPeriod(string id, IntPtr p);
    [PreserveSig] int GetShareMode(string id, IntPtr mode);
    [PreserveSig] int SetShareMode(string id, IntPtr mode);
    [PreserveSig] int GetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string id, int fx,
                         ref PropertyKey key, out PropVariant pv);
    [PreserveSig] int SetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string id, int fx,
                         ref PropertyKey key, ref PropVariant pv);
    [PreserveSig] int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string id, int role);
    [PreserveSig] int SetEndpointVisibility(string id, int visible);
  }

  [ComImport, Guid("870af99c-171d-4f9e-af0d-e63df40c2bc9")]
  class PolicyConfigClient {}

  public class Endpoint {
    public string Id, Flow, Description, Name;
    public bool IsDefault;
  }

  public static class Endpoints {
    static PropertyKey DeviceDesc = new PropertyKey("a45c254e-df1c-4efd-8020-67d146a850e0", 2);
    static PropertyKey FriendlyName = new PropertyKey("a45c254e-df1c-4efd-8020-67d146a850e0", 14);

    static void Check(int hr, string what) {
      if (hr != 0) throw new Exception(what + " failed: 0x" + hr.ToString("X8"));
    }

    static string Read(IPropertyStore s, PropertyKey k) {
      PropVariant pv;
      if (s.GetValue(ref k, out pv) != 0 || pv.vt != 31) return "";
      return Marshal.PtrToStringUni(pv.ptr);
    }

    public static List<Endpoint> All() {
      var en = (IMMDeviceEnumerator)new MMDeviceEnumerator();
      var list = new List<Endpoint>();
      for (int flow = 0; flow < 2; flow++) {
        string def = null;
        IMMDevice d;
        if (en.GetDefaultAudioEndpoint(flow, 0, out d) == 0) d.GetId(out def);
        IMMDeviceCollection c;
        Check(en.EnumAudioEndpoints(flow, 1, out c), "EnumAudioEndpoints");
        int n; c.GetCount(out n);
        for (int i = 0; i < n; i++) {
          // An endpoint still being set up (a device just added) can
          // vanish between the count and the read: skip it.
          IMMDevice dev; string id; IPropertyStore s;
          if (c.Item(i, out dev) != 0 || dev.GetId(out id) != 0
              || dev.OpenPropertyStore(0, out s) != 0) continue;
          list.Add(new Endpoint { Id = id, Flow = flow == 0 ? "Render" : "Capture",
            Description = Read(s, DeviceDesc), Name = Read(s, FriendlyName),
            IsDefault = id == def });
        }
      }
      return list;
    }

    public static void Rename(string id, string description) {
      var pc = (IPolicyConfig)new PolicyConfigClient();
      var pv = new PropVariant { vt = 31, ptr = Marshal.StringToCoTaskMemUni(description) };
      var key = DeviceDesc;
      try { Check(pc.SetPropertyValue(id, 0, ref key, ref pv), "SetPropertyValue"); }
      finally { Marshal.FreeCoTaskMem(pv.ptr); }
    }

    public static void SetDefault(string id) {
      var pc = (IPolicyConfig)new PolicyConfigClient();
      for (int role = 0; role < 3; role++)
        Check(pc.SetDefaultEndpoint(id, role), "SetDefaultEndpoint");
    }
  }

  // devcon install <inf> <hwid>: one more root-enumerated device node,
  // driven by the INF's driver.
  public static class RootDevice {
    [StructLayout(LayoutKind.Sequential)]
    struct DevInfoData { public int cbSize; public Guid ClassGuid; public int DevInst; public IntPtr Reserved; }

    [DllImport("setupapi.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool SetupDiGetINFClassW(string inf, out Guid cls, System.Text.StringBuilder name, int size, IntPtr req);
    [DllImport("setupapi.dll", SetLastError = true)]
    static extern IntPtr SetupDiCreateDeviceInfoList(ref Guid cls, IntPtr hwnd);
    [DllImport("setupapi.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool SetupDiCreateDeviceInfoW(IntPtr set, string name, ref Guid cls, string desc, IntPtr hwnd, int flags, ref DevInfoData data);
    [DllImport("setupapi.dll", SetLastError = true)]
    static extern bool SetupDiSetDeviceRegistryPropertyW(IntPtr set, ref DevInfoData data, int prop, byte[] buf, int size);
    [DllImport("setupapi.dll", SetLastError = true)]
    static extern bool SetupDiCallClassInstaller(int dif, IntPtr set, ref DevInfoData data);
    [DllImport("setupapi.dll", SetLastError = true)]
    static extern bool SetupDiDestroyDeviceInfoList(IntPtr set);
    [DllImport("newdev.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool UpdateDriverForPlugAndPlayDevicesW(IntPtr hwnd, string hwid, string inf, int flags, out bool reboot);

    static void Check(bool ok, string what) {
      if (!ok) throw new Exception(what + " failed: error " + Marshal.GetLastWin32Error());
    }

    public static void Install(string inf, string hwid) {
      Guid cls;
      var name = new System.Text.StringBuilder(64);
      Check(SetupDiGetINFClassW(inf, out cls, name, name.Capacity, IntPtr.Zero), "SetupDiGetINFClass");
      IntPtr set = SetupDiCreateDeviceInfoList(ref cls, IntPtr.Zero);
      if (set == new IntPtr(-1)) Check(false, "SetupDiCreateDeviceInfoList");
      try {
        var data = new DevInfoData { cbSize = Marshal.SizeOf(typeof(DevInfoData)) };
        Check(SetupDiCreateDeviceInfoW(set, name.ToString(), ref cls, null, IntPtr.Zero, 1 /* DICD_GENERATE_ID */, ref data),
              "SetupDiCreateDeviceInfo");
        byte[] ids = System.Text.Encoding.Unicode.GetBytes(hwid + "\0\0");
        Check(SetupDiSetDeviceRegistryPropertyW(set, ref data, 1 /* SPDRP_HARDWAREID */, ids, ids.Length),
              "SetupDiSetDeviceRegistryProperty");
        Check(SetupDiCallClassInstaller(0x19 /* DIF_REGISTERDEVICE */, set, ref data), "DIF_REGISTERDEVICE");
      } finally { SetupDiDestroyDeviceInfoList(set); }
      bool reboot;
      Check(UpdateDriverForPlugAndPlayDevicesW(IntPtr.Zero, hwid, inf, 1 /* INSTALLFLAG_FORCE */, out reboot),
            "UpdateDriverForPlugAndPlayDevices");
      if (reboot) Console.WriteLine("driver update asks for a reboot");
    }
  }
}
'@

function Find-Endpoint([string]$what, [string]$flow) {
    $all = [PoiseCi.Endpoints]::All() | Where-Object { -not $flow -or $_.Flow -eq $flow }
    $hit = @($all | Where-Object { $_.Id -eq $what })
    if (-not $hit) { $hit = @($all | Where-Object { $_.Name -like "*$what*" }) }
    if ($hit.Count -ne 1) {
        throw "endpoint '$what': $($hit.Count) matches among: $(($all | ForEach-Object Name) -join '; ')"
    }
    $hit[0]
}

if ($AddDevice) {
    [PoiseCi.RootDevice]::Install((Resolve-Path $AddDevice).Path, $HardwareId)
    "device added: $HardwareId"
    if ($WaitName) {
        $deadline = (Get-Date).AddSeconds($WaitFor)
        while (-not ([PoiseCi.Endpoints]::All() | Where-Object Name -like "*$WaitName*")) {
            if ((Get-Date) -gt $deadline) { throw "no endpoint named *$WaitName* after $WaitFor s" }
            Start-Sleep -Milliseconds 500
        }
    }
}
foreach ($r in $Rename) {
    $old, $new = $r -split '=', 2
    $ep = Find-Endpoint $old
    [PoiseCi.Endpoints]::Rename($ep.Id, $new)
    "renamed '$($ep.Name)' -> '$new'"
}
if ($Default) {
    $ep = Find-Endpoint $Default 'Render'
    [PoiseCi.Endpoints]::SetDefault($ep.Id)
    "default render endpoint: $($ep.Name)"
}
if ($List -or (-not $Rename -and -not $Default -and -not $AddDevice)) {
    [PoiseCi.Endpoints]::All() | Format-Table Flow, IsDefault, Name, Description, Id -AutoSize | Out-String -Width 300
}
