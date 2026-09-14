import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

class SttService {
  final String baseUrl;
  final http.Client _client;

  SttService({
    required this.baseUrl,
    http.Client? client,
  }) : _client = client ?? http.Client();

  Future<String> transcribe(
    Uint8List audioBytes, {
    String filename = 'speech.wav',
  }) async {
    if (audioBytes.isEmpty) {
      throw ArgumentError('STT 음성 데이터는 비어 있을 수 없습니다.');
    }

    final cleanBaseUrl = baseUrl.trim().replaceFirst(RegExp(r'/+$'), '');

    if (cleanBaseUrl.isEmpty) {
      throw StateError('STT 서버 URL이 설정되지 않았습니다.');
    }

    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$cleanBaseUrl/stt'),
    );

    request.files.add(
      http.MultipartFile.fromBytes(
        'audio',
        audioBytes,
        filename: filename,
      ),
    );

    final streamedResponse = await _client.send(request).timeout(
          const Duration(seconds: 30),
        );

    final response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode != 200) {
      throw StateError(
        'STT 요청 실패: HTTP ${response.statusCode}',
      );
    }

    final decoded = jsonDecode(
      utf8.decode(response.bodyBytes),
    );

    if (decoded is! Map<String, dynamic>) {
      throw StateError('STT 응답 형식이 올바르지 않습니다.');
    }

    final value = decoded['text'] ?? decoded['transcript'];

    if (value is! String || value.trim().isEmpty) {
      throw StateError('STT 인식 결과가 비어 있습니다.');
    }

    return value.trim();
  }

  void dispose() {
    _client.close();
  }
}
