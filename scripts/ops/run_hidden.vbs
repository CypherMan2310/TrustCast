' Run scripts\ops\run_job.cmd <job> without a console window (Task Scheduler action), so the
' scheduled jobs cannot be interrupted by closing a window. Exit code is passed through.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
runner = fso.BuildPath(here, "run_job.cmd")
rc = sh.Run("cmd.exe /c """ & runner & """ " & WScript.Arguments(0), 0, True)
WScript.Quit rc
