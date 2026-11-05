// EXHALE's native Windows launcher and transactional uv runtime setup.
// Uses only Windows' .NET Framework; no Python is needed before installation.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class RuntimeSetup
{
    readonly string root, payload, runtime;
    readonly Action<string> log;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    internal Action<string, string[], bool> Execute;

    internal RuntimeSetup(string root, string payload, Action<string> log)
    {
        this.root = Path.GetFullPath(root);
        this.payload = Path.GetFullPath(payload);
        runtime = Path.Combine(this.root, "runtime");
        this.log = log;
        Execute = Run;
    }
    internal static string ExtendedPath(string path)
    {
        if (path.StartsWith(@"\\?\")) return path;
        string full = Path.GetFullPath(path);
        return full.StartsWith(@"\\") ? @"\\?\UNC\" + full.Substring(2) : @"\\?\" + full;
    }
    static void DeleteTree(string path)
    {
        // TensorFlow headers exceed MAX_PATH even in a normal installation folder.
        string fullPath = ExtendedPath(path);
        string operation = "read attributes";
        FileAttributes attributes = 0;
        try
        {
            attributes = File.GetAttributes(fullPath);
            bool directory = (attributes & FileAttributes.Directory) != 0;
            // Never traverse junctions or symbolic links into their targets.
            if (directory && (attributes & FileAttributes.ReparsePoint) == 0)
            {
                operation = "enumerate directory";
                foreach (string entry in Directory.GetFileSystemEntries(fullPath)) DeleteTree(entry);
            }
            operation = directory ? "remove directory or directory link" : "delete file or file link";
            if (directory) Directory.Delete(fullPath, false);
            else File.Delete(fullPath);
        }
        catch (Exception error)
        {
            if (!(error is IOException) && !(error is UnauthorizedAccessException)) throw;
            throw new IOException("Runtime cleanup failed: operation=" + operation +
                "; path=" + fullPath + "; attributes=" + attributes +
                "; HRESULT=0x" + error.HResult.ToString("X8"), error);
        }
    }
    internal static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            result.Append('\\', c == '"' ? slashes * 2 + 1 : slashes);
            result.Append(c);
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }
    Dictionary<string, string> Read(string path)
    {
        return File.Exists(path) ? json.Deserialize<Dictionary<string, string>>(File.ReadAllText(path)) : null;
    }
    void Write(string path, Dictionary<string, string> state)
    {
        string temporary = path + ".tmp";
        File.WriteAllText(temporary, json.Serialize(state));
        if (File.Exists(path)) File.Replace(temporary, path, null);
        else File.Move(temporary, path);
    }
    string EnvironmentPath(Dictionary<string, string> state)
    {
        string name = state["environment"];
        if (!name.StartsWith("env-") || name != Path.GetFileName(name))
            throw new InvalidDataException("Invalid runtime environment record.");
        return Path.Combine(runtime, name);
    }
    internal static string[] Extras(string selection)
    {
        switch (selection)
        {
            case "none": return new string[0];
            case "stardist": return new[] { "stardist" };
            case "cellpose": return new[] { "cellpose" };
            case "both": return new[] { "stardist", "cellpose" };
            default: throw new ArgumentException("Unknown segmentation selection: " + selection);
        }
    }
    internal FileStream Lock()
    {
        Directory.CreateDirectory(root);
        try { return new FileStream(Path.Combine(root, "runtime.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
        catch (IOException e) { throw new IOException("EXHALE or its setup is already running. Close it first.", e); }
    }
    void Run(string executable, string[] arguments, bool startupCheck)
    {
        log("Running: " + executable + " " + String.Join(" ", arguments.Select(Quote)));
        var info = new ProcessStartInfo(executable, String.Join(" ", arguments.Select(Quote)));
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.RedirectStandardInput = true;
        foreach (string key in info.EnvironmentVariables.Keys.Cast<string>().ToArray())
            if (key.StartsWith("UV_") || key.StartsWith("PIP_") || key.StartsWith("PYTHON") ||
                key == "VIRTUAL_ENV" || key == "QT_API" || key == "QT_PLUGIN_PATH" || key == "QT_QPA_PLATFORM_PLUGIN_PATH")
                info.EnvironmentVariables.Remove(key);
        info.EnvironmentVariables["UV_PYTHON_INSTALL_DIR"] = Path.Combine(runtime, "python");
        info.EnvironmentVariables["UV_PYTHON_BIN_DIR"] = Path.Combine(runtime, "bin");
        info.EnvironmentVariables["UV_CACHE_DIR"] = Path.Combine(runtime, "cache");
        info.EnvironmentVariables["UV_PYTHON_PREFERENCE"] = "only-managed";
        info.EnvironmentVariables["UV_NO_CONFIG"] = "1";
        info.EnvironmentVariables["UV_NO_PROGRESS"] = "1";
        info.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
        info.EnvironmentVariables["QT_API"] = "pyqt6";
        if (startupCheck) info.EnvironmentVariables["QT_QPA_PLATFORM"] = "offscreen";
        using (var process = new Process())
        {
            process.StartInfo = info;
            process.OutputDataReceived += (s, e) => { if (e.Data != null) log(e.Data); };
            process.ErrorDataReceived += (s, e) => { if (e.Data != null) log(e.Data); };
            process.Start();
            process.StandardInput.Close();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            process.WaitForExit();
            if (process.ExitCode != 0)
                throw new InvalidOperationException(Path.GetFileName(executable) + " failed (exit " + process.ExitCode + "). See the installation log.");
        }
    }
    internal void Discard(bool removeUnusedRuntime = false)
    {
        string pendingPath = Path.Combine(runtime, "pending.json");
        var pending = Read(pendingPath);
        var active = Read(Path.Combine(runtime, "installed.json"));
        if (pending != null)
        {
            string path = EnvironmentPath(pending);
            if ((active == null || active["environment"] != pending["environment"]) && Directory.Exists(path))
                DeleteTree(path);
            File.Delete(pendingPath);
        }
        if (removeUnusedRuntime && active == null && Directory.Exists(runtime))
            DeleteTree(runtime);
    }
    internal void Remove()
    {
        log("Removing private runtime: " + runtime);
        if (Directory.Exists(runtime)) DeleteTree(runtime);
        log("Private runtime removed. Projects, trained models and application settings were retained.");
    }
    internal void Prepare(string selection)
    {
        string[] extras = Extras(selection);
        Directory.CreateDirectory(runtime);
        Discard();
        string environment = Path.Combine(runtime, "env-" + Guid.NewGuid().ToString("N"));
        var config = Read(Path.Combine(payload, "setup.json"));
        string wheel = Path.Combine(payload, config["wheel"]);
        if (!File.Exists(wheel)) throw new FileNotFoundException("Bundled EXHALE wheel is missing.", wheel);
        string uv = Path.Combine(payload, "uv.exe");
        try
        {
            Execute(uv, new[] { "venv", "--python", "3.11", environment }, false);
            var command = new List<string> { "pip", "install", "--python", Path.Combine(environment, "Scripts", "python.exe"),
                "--prerelease", "disallow", wheel + (extras.Length == 0 ? "" : "[" + String.Join(",", extras) + "]") };
            if (extras.Contains("cellpose")) command.AddRange(new[] { "-r", Path.Combine(payload, "requirements-cellpose.txt") });
            Execute(uv, command.ToArray(), false);
            Execute(Path.Combine(environment, "Scripts", "python.exe"), new[] { "-m", "exhale", "--startup-check" }, true);
            Write(Path.Combine(runtime, "pending.json"), new Dictionary<string, string> {
                { "environment", Path.GetFileName(environment) }, { "wheel", config["wheel"] }, { "backends", selection } });
            log("Runtime validated. Ready to finish installation.");
        }
        catch
        {
            if (Directory.Exists(environment)) DeleteTree(environment);
            throw;
        }
    }
    internal void Activate()
    {
        string pendingPath = Path.Combine(runtime, "pending.json");
        var pending = Read(pendingPath);
        if (pending == null) throw new InvalidOperationException("No prepared runtime was found.");
        var config = Read(Path.Combine(payload, "setup.json"));
        if (config["wheel"] != pending["wheel"]) throw new InvalidOperationException("Prepared runtime belongs to a different release.");
        string statePath = Path.Combine(runtime, "installed.json");
        var previous = Read(statePath);
        Write(statePath, pending);
        File.Delete(pendingPath);
        if (previous != null && previous["environment"] != pending["environment"])
        {
            try { DeleteTree(EnvironmentPath(previous)); }
            catch (IOException e) { log("Installed successfully; old runtime cleanup failed for " + EnvironmentPath(previous) + ": " + e); }
            catch (UnauthorizedAccessException e) { log("Installed successfully; old runtime cleanup failed for " + EnvironmentPath(previous) + ": " + e); }
        }
        log("Installation complete.");
    }
    internal void Launch(string[] arguments)
    {
        if (File.Exists(Path.Combine(runtime, "pending.json")))
            throw new InvalidOperationException("EXHALE setup is in progress. Finish or close setup first.");
        var state = Read(Path.Combine(runtime, "installed.json"));
        if (state == null) throw new InvalidOperationException("Please run the EXHALE installer first.");
        Execute(Path.Combine(EnvironmentPath(state), "Scripts", "python.exe"),
            new[] { "-m", "exhale" }.Concat(arguments).ToArray(), arguments.Contains("--startup-check"));
    }
    internal static void SelfTest()
    {
        if (Quote("a b") != "\"a b\"" || Quote("a\"b") != "\"a\\\"b\"" || Quote("c:\\") != "\"c:\\\\\"")
            throw new Exception("Windows argument quoting failed.");
        string directory = Path.Combine(Path.GetTempPath(), "exhale-native-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            string longRoot = Path.Combine(directory, "long-path-test");
            string longDirectory = Path.Combine(longRoot, new string('a', 120), new string('b', 120));
            string longFile = Path.Combine(longDirectory, "bufferizable_op_interface_impl.h");
            if (longFile.Length <= 300) throw new Exception("Long-path test is not long enough.");
            Directory.CreateDirectory(ExtendedPath(longDirectory));
            File.WriteAllText(ExtendedPath(longFile), "header");
            DeleteTree(longRoot);
            if (Directory.Exists(longRoot)) throw new Exception("Long-path deletion failed.");
            string target = Path.Combine(directory, "junction-target");
            Directory.CreateDirectory(target);
            string sentinel = Path.Combine(target, "preserve.txt");
            File.WriteAllText(sentinel, "outside the deleted tree");
            string junctionRoot = Path.Combine(directory, "junction-test");
            Directory.CreateDirectory(junctionRoot);
            string junction = Path.Combine(junctionRoot, "linked-directory");
            var linkInfo = new ProcessStartInfo(Environment.GetEnvironmentVariable("ComSpec"),
                "/d /c mklink /J " + Quote(junction) + " " + Quote(target));
            linkInfo.UseShellExecute = false;
            linkInfo.CreateNoWindow = true;
            using (var process = Process.Start(linkInfo))
            {
                process.WaitForExit();
                if (process.ExitCode != 0) throw new Exception("Could not create the junction test fixture.");
            }
            if ((File.GetAttributes(junction) & FileAttributes.ReparsePoint) == 0)
                throw new Exception("Junction test fixture is not a reparse point.");
            DeleteTree(junctionRoot);
            if (Directory.Exists(junctionRoot) || File.ReadAllText(sentinel) != "outside the deleted tree")
                throw new Exception("Junction cleanup followed the link or left the deleted tree behind.");
            string lockedRoot = Path.Combine(directory, "locked-file-test");
            Directory.CreateDirectory(lockedRoot);
            string lockedFile = Path.Combine(lockedRoot, "locked.txt");
            using (var stream = new FileStream(lockedFile, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                try { DeleteTree(lockedRoot); throw new Exception("Locked-file deletion unexpectedly succeeded."); }
                catch (IOException error)
                {
                    string report = error.ToString();
                    if (!report.Contains(ExtendedPath(lockedFile)) ||
                        !report.Contains("operation=delete file or file link") || !report.Contains("HRESULT=0x"))
                        throw new Exception("Cleanup failure omitted the offending path or operation.", error);
                }
            }
            DeleteTree(lockedRoot);
            foreach (string selection in new[] { "none", "stardist", "cellpose", "both" })
            {
                string home = Path.Combine(directory, selection);
                Directory.CreateDirectory(home);
                var setup = new RuntimeSetup(home, directory, s => { });
                File.WriteAllText(Path.Combine(directory, "setup.json"), "{\"wheel\":\"test.whl\"}");
                File.WriteAllText(Path.Combine(directory, "test.whl"), "test");
                var calls = new List<string[]>();
                setup.Execute = (exe, args, check) => { calls.Add(args); if (args[0] == "venv") Directory.CreateDirectory(args[3]); };
                using (setup.Lock())
                {
                    setup.Prepare(selection);
                    if (File.Exists(Path.Combine(home, "runtime", "installed.json"))) throw new Exception("Premature activation.");
                    if (calls[1].Contains("-r") != Extras(selection).Contains("cellpose")) throw new Exception("Backend selection failed.");
                    string expectedExtras = Extras(selection).Length == 0 ? "test.whl" : "test.whl[" + String.Join(",", Extras(selection)) + "]";
                    if (!calls[1][6].EndsWith(expectedExtras)) throw new Exception("Wrong wheel extras.");
                    setup.Activate();
                    string before = File.ReadAllText(Path.Combine(home, "runtime", "installed.json"));
                    setup.Execute = (exe, args, check) => {
                        if (args[0] == "venv") Directory.CreateDirectory(args[3]);
                        if (check) throw new InvalidOperationException("simulated startup failure");
                    };
                    try { setup.Prepare(selection); throw new Exception("Failed setup was accepted."); }
                    catch (InvalidOperationException) { }
                    if (before != File.ReadAllText(Path.Combine(home, "runtime", "installed.json"))) throw new Exception("Failed update changed the active environment.");
                    setup.Execute = (exe, args, check) => { if (args[0] == "venv") Directory.CreateDirectory(args[3]); };
                    setup.Prepare(selection);
                    setup.Discard();
                    if (before != File.ReadAllText(Path.Combine(home, "runtime", "installed.json"))) throw new Exception("Cancelled update changed the active environment.");
                    setup.Prepare(selection);
                    setup.Activate();
                    if (Directory.GetDirectories(Path.Combine(home, "runtime"), "env-*").Length != 1)
                        throw new Exception("Successful update did not retire the old environment.");
                    string userFile = Path.Combine(home, "user-project.h5");
                    File.WriteAllText(userFile, "user data");
                    string deepCache = Path.Combine(home, "runtime", "cache", new string('c', 120), new string('d', 120));
                    Directory.CreateDirectory(ExtendedPath(deepCache));
                    File.WriteAllText(ExtendedPath(Path.Combine(deepCache, "header.h")), "header");
                    setup.Remove();
                    if (Directory.Exists(Path.Combine(home, "runtime"))) throw new Exception("Runtime removal failed.");
                    if (File.ReadAllText(userFile) != "user data") throw new Exception("Runtime removal affected user files.");
                }
            }
        }
        finally { DeleteTree(directory); }
    }
}

internal static class Launcher
{
    [STAThread]
    static int Main(string[] args)
    {
        // Set before any System.IO operation; no machine-wide policy change is needed.
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
        AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
        string payload = AppDomain.CurrentDomain.BaseDirectory;
        string root = payload;
        int rootIndex = Array.IndexOf(args, "--install-root");
        if (rootIndex >= 0 && rootIndex + 1 < args.Length) root = args[rootIndex + 1];
        bool quiet = args.Contains("--quiet") || args.Contains("--startup-check") || args.Contains("--self-test");
        string logPath = Path.Combine(root, "runtime.log");
        try
        {
            if (args.Contains("--self-test")) { RuntimeSetup.SelfTest(); return 0; }
            Directory.CreateDirectory(root);
            using (var mutex = new Mutex(false, "EXHALEDesktopRuntime"))
            using (var stream = new StreamWriter(new FileStream(logPath, FileMode.Append, FileAccess.Write, FileShare.ReadWrite)))
            {
                stream.AutoFlush = true;
                Action<string> log = text => { lock (stream) stream.WriteLine(text); };
                var setup = new RuntimeSetup(root, payload, log);
                Func<int> operation = () => {
                    using (setup.Lock())
                    {
                        if (args.Contains("--prepare-install")) setup.Prepare(args[Array.IndexOf(args, "--prepare-install") + 1]);
                        else if (args.Contains("--activate-install")) setup.Activate();
                        else if (args.Contains("--discard-install")) setup.Discard(true);
                        else if (args.Contains("--remove-runtime")) setup.Remove();
                        else setup.Launch(args);
                    }
                    return 0;
                };
                if (!quiet && args.Contains("--prepare-install"))
                {
                    Application.EnableVisualStyles();
                    var form = new Form { Text = "Installing EXHALE", Width = 760, Height = 440, StartPosition = FormStartPosition.CenterScreen };
                    var output = new TextBox { Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical };
                    form.Controls.Add(output);
                    bool complete = false;
                    form.FormClosing += (s, e) => { if (!complete) e.Cancel = true; };
                    setup = new RuntimeSetup(root, payload, text => {
                        log(text);
                        form.BeginInvoke(new Action(() => { output.AppendText(text + Environment.NewLine); }));
                    });
                    Exception failure = null;
                    form.Shown += (s, e) => Task.Run(() => {
                        try { operation(); } catch (Exception error) { failure = error; }
                        form.BeginInvoke(new Action(() => { complete = true; form.Close(); }));
                    });
                    Application.Run(form);
                    if (failure != null) throw failure;
                    return 0;
                }
                return operation();
            }
        }
        catch (Exception error)
        {
            try { File.AppendAllText(logPath, error.ToString() + Environment.NewLine); } catch (Exception) { }
            if (!quiet && !args.Contains("--prepare-install")) MessageBox.Show(error.Message + "\n\nLog: " + logPath, "EXHALE", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
