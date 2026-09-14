import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:safehub_app/services/tts_service.dart';

void main() {
  test('정상 요청은 앞뒤 공백을 제거하고 음성 bytes를 반환한다', () async {
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.toString(), 'http://localhost:5001/tts');
      expect(request.headers['Content-Type'], contains('application/json'));

      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body['text'], '안녕하세요');

      return http.Response.bytes(
        [1, 2, 3, 4],
        200,
        headers: {
          'content-type': 'audio/mpeg',
        },
      );
    });

    final service = TtsService(
      baseUrl: 'http://localhost:5001/',
      client: client,
    );

    final bytes = await service.synthesize('  안녕하세요  ');

    expect(bytes, [1, 2, 3, 4]);
    service.dispose();
  });

  test('빈 텍스트는 요청 전에 거부한다', () async {
    final client = MockClient((request) async {
      fail('빈 텍스트는 HTTP 요청을 보내면 안 됩니다.');
    });

    final service = TtsService(
      baseUrl: 'http://localhost:5001',
      client: client,
    );

    await expectLater(
      service.synthesize('   '),
      throwsArgumentError,
    );

    service.dispose();
  });

  test('서버 URL이 비어 있으면 오류를 발생시킨다', () async {
    final service = TtsService(
      baseUrl: '   ',
      client: MockClient((request) async {
        fail('URL이 없으면 HTTP 요청을 보내면 안 됩니다.');
      }),
    );

    await expectLater(
      service.synthesize('테스트'),
      throwsStateError,
    );

    service.dispose();
  });

  test('HTTP 오류 응답을 거부한다', () async {
    final service = TtsService(
      baseUrl: 'http://localhost:5001',
      client: MockClient((request) async {
        return http.Response('server error', 500);
      }),
    );

    await expectLater(
      service.synthesize('테스트'),
      throwsStateError,
    );

    service.dispose();
  });

  test('비어 있는 음성 응답을 거부한다', () async {
    final service = TtsService(
      baseUrl: 'http://localhost:5001',
      client: MockClient((request) async {
        return http.Response.bytes([], 200);
      }),
    );

    await expectLater(
      service.synthesize('테스트'),
      throwsStateError,
    );

    service.dispose();
  });
}
