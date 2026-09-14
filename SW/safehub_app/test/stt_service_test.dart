import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:safehub_app/services/stt_service.dart';

void main() {
  test('WAV 파일을 multipart로 전송하고 text를 반환한다', () async {
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.toString(), 'http://localhost:5002/stt');
      expect(
        request.headers['content-type'],
        startsWith('multipart/form-data'),
      );
      expect(request.body, contains('name="audio"'));
      expect(request.body, contains('filename="speech.wav"'));

      return http.Response(
        jsonEncode({
          'text': ' 안녕하세요 ',
        }),
        200,
        headers: {
          'content-type': 'application/json',
        },
      );
    });

    final service = SttService(
      baseUrl: 'http://localhost:5002/',
      client: client,
    );

    final text = await service.transcribe(
      Uint8List.fromList([1, 2, 3, 4]),
    );

    expect(text, '안녕하세요');
    service.dispose();
  });

  test('transcript 응답 필드도 처리한다', () async {
    final service = SttService(
      baseUrl: 'http://localhost:5002',
      client: MockClient((request) async {
        return http.Response(
          jsonEncode({
            'transcript': '도와주세요',
          }),
          200,
          headers: {
            'content-type': 'application/json; charset=utf-8',
          },
        );
      }),
    );

    final text = await service.transcribe(
      Uint8List.fromList([1]),
    );

    expect(text, '도와주세요');
    service.dispose();
  });

  test('빈 음성 데이터는 요청 전에 거부한다', () async {
    final service = SttService(
      baseUrl: 'http://localhost:5002',
      client: MockClient((request) async {
        fail('빈 음성은 HTTP 요청을 보내면 안 됩니다.');
      }),
    );

    await expectLater(
      service.transcribe(Uint8List(0)),
      throwsArgumentError,
    );

    service.dispose();
  });

  test('STT 서버 URL이 비어 있으면 오류가 발생한다', () async {
    final service = SttService(
      baseUrl: '',
      client: MockClient((request) async {
        fail('URL이 없으면 HTTP 요청을 보내면 안 됩니다.');
      }),
    );

    await expectLater(
      service.transcribe(Uint8List.fromList([1])),
      throwsStateError,
    );

    service.dispose();
  });

  test('HTTP 오류 응답을 거부한다', () async {
    final service = SttService(
      baseUrl: 'http://localhost:5002',
      client: MockClient((request) async {
        return http.Response('server error', 500);
      }),
    );

    await expectLater(
      service.transcribe(Uint8List.fromList([1])),
      throwsStateError,
    );

    service.dispose();
  });

  test('비어 있는 인식 결과를 거부한다', () async {
    final service = SttService(
      baseUrl: 'http://localhost:5002',
      client: MockClient((request) async {
        return http.Response(
          jsonEncode({
            'text': '   ',
          }),
          200,
        );
      }),
    );

    await expectLater(
      service.transcribe(Uint8List.fromList([1])),
      throwsStateError,
    );

    service.dispose();
  });

  test('JSON이 아닌 응답을 거부한다', () async {
    final service = SttService(
      baseUrl: 'http://localhost:5002',
      client: MockClient((request) async {
        return http.Response('not json', 200);
      }),
    );

    await expectLater(
      service.transcribe(Uint8List.fromList([1])),
      throwsA(isA<FormatException>()),
    );

    service.dispose();
  });
}
