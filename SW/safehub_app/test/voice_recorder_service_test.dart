import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:safehub_app/services/voice_recorder_service.dart';

class FakeRecorderBackend implements VoiceRecorderBackend {
  bool permission = true;
  bool wavSupported = true;
  bool recording = false;
  bool disposed = false;
  String? recordedPath;
  List<int> outputBytes = [82, 73, 70, 70];

  @override
  Future<bool> hasPermission() async => permission;

  @override
  Future<bool> supportsWav() async => wavSupported;

  @override
  Future<bool> isRecording() async => recording;

  @override
  Future<void> start(String path) async {
    recordedPath = path;
    recording = true;
  }

  @override
  Future<String?> stop() async {
    final path = recordedPath;
    recording = false;

    if (path != null) {
      await File(path).writeAsBytes(outputBytes);
    }

    return path;
  }

  @override
  Future<void> cancel() async {
    recording = false;
  }

  @override
  Future<void> dispose() async {
    disposed = true;
  }
}

void main() {
  late Directory temporaryDirectory;
  late FakeRecorderBackend backend;
  late VoiceRecorderService service;

  setUp(() async {
    temporaryDirectory =
        await Directory.systemTemp.createTemp('safehub_recorder_test_');

    backend = FakeRecorderBackend();

    service = VoiceRecorderService(
      backend: backend,
      directoryProvider: () async => temporaryDirectory,
    );
  });

  tearDown(() async {
    await service.dispose();

    if (await temporaryDirectory.exists()) {
      await temporaryDirectory.delete(recursive: true);
    }
  });

  test('WAV 녹음을 시작하고 파일 경로를 생성한다', () async {
    final path = await service.start();

    expect(path, endsWith('.wav'));
    expect(path, contains(temporaryDirectory.path));
    expect(backend.recording, true);
    expect(backend.recordedPath, path);
  });

  test('마이크 권한이 없으면 녹음을 시작하지 않는다', () async {
    backend.permission = false;

    await expectLater(
      service.start(),
      throwsStateError,
    );

    expect(backend.recording, false);
  });

  test('WAV를 지원하지 않으면 녹음을 시작하지 않는다', () async {
    backend.wavSupported = false;

    await expectLater(
      service.start(),
      throwsStateError,
    );

    expect(backend.recording, false);
  });

  test('이미 녹음 중이면 중복 시작을 거부한다', () async {
    await service.start();

    await expectLater(
      service.start(),
      throwsStateError,
    );
  });

  test('녹음을 종료하고 WAV bytes를 반환한다', () async {
    await service.start();

    final bytes = await service.stopAndRead();

    expect(bytes, backend.outputBytes);
    expect(backend.recording, false);
  });

  test('녹음 중이 아니면 종료를 거부한다', () async {
    await expectLater(
      service.stopAndRead(),
      throwsStateError,
    );
  });

  test('빈 녹음 파일은 거부한다', () async {
    backend.outputBytes = [];
    await service.start();

    await expectLater(
      service.stopAndRead(),
      throwsStateError,
    );
  });

  test('취소하면 녹음 상태가 종료된다', () async {
    await service.start();
    await service.cancel();

    expect(await service.isRecording, false);
  });

  test('dispose가 녹음 backend를 정리한다', () async {
    await service.dispose();

    expect(backend.disposed, true);
  });
}
