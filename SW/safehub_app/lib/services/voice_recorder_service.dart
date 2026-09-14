import 'dart:io';
import 'dart:typed_data';

import 'package:record/record.dart';

abstract interface class VoiceRecorderBackend {
  Future<bool> hasPermission();
  Future<bool> supportsWav();
  Future<bool> isRecording();
  Future<void> start(String path);
  Future<String?> stop();
  Future<void> cancel();
  Future<void> dispose();
}

class AtlasVoiceRecorderBackend implements VoiceRecorderBackend {
  final AudioRecorder _recorder = AudioRecorder();

  @override
  Future<bool> hasPermission() {
    return _recorder.hasPermission();
  }

  @override
  Future<bool> supportsWav() {
    return _recorder.isEncoderSupported(AudioEncoder.wav);
  }

  @override
  Future<bool> isRecording() {
    return _recorder.isRecording();
  }

  @override
  Future<void> start(String path) {
    return _recorder.start(
      const RecordConfig(
        encoder: AudioEncoder.wav,
        sampleRate: 16000,
        numChannels: 1,
        noiseSuppress: true,
      ),
      path: path,
    );
  }

  @override
  Future<String?> stop() {
    return _recorder.stop();
  }

  @override
  Future<void> cancel() {
    return _recorder.cancel();
  }

  @override
  Future<void> dispose() {
    return _recorder.dispose();
  }
}

typedef RecordingDirectoryProvider = Future<Directory> Function();

class VoiceRecorderService {
  final VoiceRecorderBackend _backend;
  final RecordingDirectoryProvider _directoryProvider;

  VoiceRecorderService({
    VoiceRecorderBackend? backend,
    RecordingDirectoryProvider? directoryProvider,
  })  : _backend = backend ?? AtlasVoiceRecorderBackend(),
        _directoryProvider = directoryProvider ?? _defaultRecordingDirectory;

  static Future<Directory> _defaultRecordingDirectory() async {
    final home = Platform.environment['HOME']?.trim();
    final base = home == null || home.isEmpty ? '/tmp' : home;

    final directory = Directory('$base/safehub_recordings');

    if (!await directory.exists()) {
      await directory.create(recursive: true);
    }

    return directory;
  }

  Future<String> start() async {
    if (await _backend.isRecording()) {
      throw StateError('이미 음성을 녹음하고 있습니다.');
    }

    if (!await _backend.hasPermission()) {
      throw StateError('마이크 사용 권한이 없습니다.');
    }

    if (!await _backend.supportsWav()) {
      throw StateError('이 장치에서 WAV 녹음을 지원하지 않습니다.');
    }

    final directory = await _directoryProvider();

    if (!await directory.exists()) {
      await directory.create(recursive: true);
    }

    final timestamp = DateTime.now().microsecondsSinceEpoch;
    final path = '${directory.path}/safehub_speech_$timestamp.wav';

    await _backend.start(path);
    return path;
  }

  Future<Uint8List> stopAndRead() async {
    if (!await _backend.isRecording()) {
      throw StateError('진행 중인 음성 녹음이 없습니다.');
    }

    final path = await _backend.stop();

    if (path == null || path.trim().isEmpty) {
      throw StateError('녹음 파일 경로를 받지 못했습니다.');
    }

    final file = File(path);

    if (!await file.exists()) {
      throw StateError('녹음 파일을 찾을 수 없습니다.');
    }

    final bytes = await file.readAsBytes();

    if (bytes.isEmpty) {
      throw StateError('녹음 파일이 비어 있습니다.');
    }

    return bytes;
  }

  Future<void> cancel() {
    return _backend.cancel();
  }

  Future<bool> get isRecording {
    return _backend.isRecording();
  }

  Future<void> dispose() {
    return _backend.dispose();
  }
}
