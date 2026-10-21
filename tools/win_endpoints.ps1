<#
.SYNOPSIS
  List Windows audio endpoints and pick the default output (CI helper).

.DESCRIPTION
  The hosted Windows runner has no sound card: CI installs virtual cables
  (.github/actions/windows-audio) and needs to see them and choose which
  one plays by default, as a user would in the Sound settings. Setting
  the default uses the endpoint builder's policy interface (what the
  Sound control panel calls), so it needs an elevated shell.

  -List            print every active render/capture endpoint
  -Default <name>  make the render endpoint whose name contains <name>
                   the default for every role (exactly one must match)
#>
param(
    [switch]$List,
    [string]$Default
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

  // Undocumented, stable since Vista: what mmsys.cpl uses to set the
  // default endpoint.
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

    public static void SetDefault(string id) {
      var pc = (IPolicyConfig)new PolicyConfigClient();
      for (int role = 0; role < 3; role++)
        Check(pc.SetDefaultEndpoint(id, role), "SetDefaultEndpoint");
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

if ($Default) {
    $ep = Find-Endpoint $Default 'Render'
    [PoiseCi.Endpoints]::SetDefault($ep.Id)
    "default render endpoint: $($ep.Name)"
}
if ($List -or -not $Default) {
    [PoiseCi.Endpoints]::All() | Format-Table Flow, IsDefault, Name, Description, Id -AutoSize | Out-String -Width 300
}
