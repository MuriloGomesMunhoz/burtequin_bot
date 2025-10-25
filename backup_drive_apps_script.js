// Google Apps Script: mantém apenas os últimos N backups na pasta "Burtequin Backups"
function manterBackups() {
  var folderName = "Burtequin Backups";
  var limit = 30;
  var folders = DriveApp.getFoldersByName(folderName);
  var folder = folders.hasNext() ? folders.next() : DriveApp.createFolder(folderName);
  var files = [];
  var it = folder.getFiles();
  while (it.hasNext()) { files.push(it.next()); }
  files.sort(function(a,b){ return b.getDateCreated() - a.getDateCreated(); });
  for (var i=limit; i<files.length; i++) { files[i].setTrashed(true); }
}