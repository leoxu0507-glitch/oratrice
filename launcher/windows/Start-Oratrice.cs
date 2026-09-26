using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

internal static class StartOratrice
{
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const int JobObjectExtendedLimitInformation = 9;

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll")]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);
    [DllImport("kernel32.dll")]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        string script = Path.Combine(root, "scripts", "launch_oratrice.py");
        if (!File.Exists(script)) return Fail("Missing launcher script: " + script);
        string python = FindPython();
        if (python == null) return Fail("No usable Python found. Set ORATRICE_PYTHON.");

        ProcessStartInfo info = new ProcessStartInfo();
        info.FileName = python;
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.CreateNoWindow = false;
        info.Arguments = Quote(script) + Forward(args);
        IntPtr job = CreateKillJob();
        try
        {
            using (Process child = Process.Start(info))
            {
                if (child == null) return Fail("Could not start the Python launcher.");
                if (job != IntPtr.Zero && !AssignProcessToJobObject(job, child.Handle))
                    Console.WriteLine("Warning: process-tree safety job could not be assigned.");
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception ex) { return Fail("Launcher failed: " + ex.GetType().Name); }
        finally { if (job != IntPtr.Zero) CloseHandle(job); }
    }

    private static string FindPython()
    {
        string configured = Environment.GetEnvironmentVariable("ORATRICE_PYTHON");
        if (!String.IsNullOrWhiteSpace(configured))
        {
            configured = configured.Trim();
            if (!IsAbsolutePath(configured))
            {
                Console.Error.WriteLine("ORATRICE_PYTHON must be an absolute path to an existing Python executable.");
                return null;
            }

            if (!File.Exists(configured))
            {
                Console.Error.WriteLine("ORATRICE_PYTHON does not exist: " + configured);
                return null;
            }

            return Path.GetFullPath(configured);
        }

        string root = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory);
        string projectPython = Path.Combine(root, @".venv\Scripts\python.exe");
        if (File.Exists(projectPython)) return projectPython;

        string infrastructurePython = Path.GetFullPath(
            Path.Combine(root, @"..\..\infrastructure\litellm\.venv\Scripts\python.exe"));
        if (File.Exists(infrastructurePython)) return infrastructurePython;

        return FindOnPath("python.exe");
    }

    private static bool IsAbsolutePath(string value)
    {
        if (!Path.IsPathRooted(value)) return false;
        string root = Path.GetPathRoot(value);
        return !String.IsNullOrEmpty(root) && root.Length > 2;
    }

    private static string FindOnPath(string executable)
    {
        string path = Environment.GetEnvironmentVariable("PATH");
        if (String.IsNullOrWhiteSpace(path)) return null;

        string[] directories = path.Split(new[] { Path.PathSeparator }, StringSplitOptions.RemoveEmptyEntries);
        foreach (string directory in directories)
        {
            string trimmed = directory.Trim().Trim('"');
            if (trimmed.Length == 0) continue;

            string candidate;
            try
            {
                candidate = Path.GetFullPath(Path.Combine(trimmed, executable));
            }
            catch (ArgumentException)
            {
                continue;
            }

            if (File.Exists(candidate)) return candidate;
        }

        return null;
    }

    private static IntPtr CreateKillJob()
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) return IntPtr.Zero;
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        IntPtr pointer = Marshal.AllocHGlobal(length);
        try
        {
            Marshal.StructureToPtr(info, pointer, false);
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, pointer, (uint)length))
            { CloseHandle(job); return IntPtr.Zero; }
            return job;
        }
        finally { Marshal.FreeHGlobal(pointer); }
    }

    private static string Quote(string value) { return "\"" + value.Replace("\"", "\\\"") + "\""; }
    private static string Forward(string[] args)
    {
        if (args.Length == 0) return "";
        List<string> values = new List<string>();
        foreach (string value in args) values.Add(" " + Quote(value));
        return String.Join("", values.ToArray());
    }
    private static int Fail(string message)
    { Console.Error.WriteLine(message); Console.WriteLine("Press any key to close."); Console.ReadKey(true); return 2; }
}
