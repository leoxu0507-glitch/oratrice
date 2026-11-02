using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static class StartOratrice
{
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const uint CREATE_SUSPENDED = 0x00000004;
    private const uint INFINITE = 0xFFFFFFFF;
    private const uint WAIT_FAILED = 0xFFFFFFFF;
    private const uint THREAD_FAILURE = 0xFFFFFFFF;
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

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow, cbReserved2;
        public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess;
        public IntPtr hThread;
        public uint dwProcessId;
        public uint dwThreadId;
    }

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CreateProcess(
        string applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref STARTUPINFO startupInfo,
        out PROCESS_INFORMATION processInformation);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateProcess(IntPtr process, uint exitCode);

    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        string script = Path.Combine(root, "scripts", "launch_oratrice.py");
        if (!File.Exists(script)) return Fail("Missing launcher script: " + script);
        string python = FindPython();
        if (python == null) return Fail("No usable Python found. Set ORATRICE_PYTHON.");

        IntPtr job = CreateKillJob();
        if (job == IntPtr.Zero)
            return Fail("Could not create the process safety job.");

        STARTUPINFO startup = new STARTUPINFO();
        startup.cb = Marshal.SizeOf(typeof(STARTUPINFO));
        PROCESS_INFORMATION process = new PROCESS_INFORMATION();
        StringBuilder commandLine = new StringBuilder(
            Quote(python) + " " + Quote(script) + Forward(args));
        bool created = false;
        try
        {
            if (!CreateProcess(
                    python,
                    commandLine,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    false,
                    CREATE_SUSPENDED,
                    IntPtr.Zero,
                    root,
                    ref startup,
                    out process))
            {
                return Fail("Could not start the Python launcher (Win32 " +
                    Marshal.GetLastWin32Error() + ").");
            }
            created = true;
            if (!AssignProcessToJobObject(job, process.hProcess))
                return AbortChild(process.hProcess, "Could not assign the launcher to the process safety job (Win32 " +
                    Marshal.GetLastWin32Error() + ").");

            if (ResumeThread(process.hThread) == THREAD_FAILURE)
                return AbortChild(process.hProcess, "Could not resume the launcher (Win32 " +
                    Marshal.GetLastWin32Error() + ").");

            CloseHandle(process.hThread);
            process.hThread = IntPtr.Zero;
            if (WaitForSingleObject(process.hProcess, INFINITE) == WAIT_FAILED)
                return Fail("Could not wait for the Python launcher (Win32 " +
                    Marshal.GetLastWin32Error() + ").");
            uint exitCode;
            if (!GetExitCodeProcess(process.hProcess, out exitCode))
                return Fail("Could not read the Python launcher exit code (Win32 " +
                    Marshal.GetLastWin32Error() + ").");
            return unchecked((int)exitCode);
        }
        catch (Exception ex) { return Fail("Launcher failed: " + ex.GetType().Name); }
        finally
        {
            if (created)
            {
                if (process.hThread != IntPtr.Zero) CloseHandle(process.hThread);
                if (process.hProcess != IntPtr.Zero) CloseHandle(process.hProcess);
            }
            CloseHandle(job);
        }
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

    private static int AbortChild(IntPtr process, string message)
    {
        if (process != IntPtr.Zero)
        {
            TerminateProcess(process, 2);
            WaitForSingleObject(process, 5000);
        }
        return Fail(message);
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
    {
        Console.Error.WriteLine(message);
        if (!Console.IsInputRedirected && !Console.IsOutputRedirected)
        {
            Console.WriteLine("Press any key to close.");
            try { Console.ReadKey(true); } catch (InvalidOperationException) { }
        }
        return 2;
    }
}
