import 'dart:io';

/// Stored in the app's own home, never /tmp. No system permission changes.
class ShortcutStore {
  final File file;
  ShortcutStore(this.file);
  factory ShortcutStore.forApp() {
    final home = Platform.environment['HOME'];
    if (home == null || home.isEmpty) throw StateError('앱 저장 경로가 없습니다');
    return ShortcutStore(File('$home/safehub_shortcuts/bindings.json'));
  }
  Future<String?> read() async => await file.exists() ? file.readAsString() : null;
  Future<void> write(String data) async {
    await file.parent.create(recursive: true);
    final temporary = File('${file.path}.new');
    await temporary.writeAsString(data, flush: true);
    await temporary.rename(file.path);
  }
}
