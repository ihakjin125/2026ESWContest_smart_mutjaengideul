import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';

class DisasterService {
  static const int _rowsPerPage = 20;

  int? _lastPage;

  Future<Map<String, dynamic>?> fetchLatest() async {
    // 처음 한 번만 전체 개수를 확인해 마지막 페이지를 계산
    if (_lastPage == null) {
      final firstResponse = await _request(pageNo: 1);

      final totalCount = firstResponse['totalCount'];

      if (totalCount is! int || totalCount <= 0) {
        return null;
      }

      _lastPage = (totalCount / _rowsPerPage).ceil();
    }

    var response = await _request(
      pageNo: _lastPage!,
    );

    final totalCount = response['totalCount'];

    if (totalCount is! int || totalCount <= 0) {
      return null;
    }

    // 조회 중 새 재난문자가 추가돼 마지막 페이지가 바뀐 경우 대응
    final newLastPage = (totalCount / _rowsPerPage).ceil();

    if (newLastPage != _lastPage) {
      _lastPage = newLastPage;

      response = await _request(
        pageNo: _lastPage!,
      );
    }

    final body = response['body'];

    if (body is! List || body.isEmpty) {
      return null;
    }

    final latest = body.last;

    if (latest is! Map<String, dynamic>) {
      return null;
    }

    return Map<String, dynamic>.from(latest);
  }

  Future<Map<String, dynamic>> _request({
    required int pageNo,
  }) async {
    final uri = Uri.parse(
      AppConfig.disasterApiUrl,
    ).replace(
      queryParameters: {
        'serviceKey': AppConfig.disasterApiKey,
        'returnType': 'json',
        'pageNo': pageNo.toString(),
        'numOfRows': _rowsPerPage.toString(),
      },
    );

    final response = await http.get(uri).timeout(
          const Duration(seconds: 10),
        );

    if (response.statusCode != 200) {
      throw Exception(
        '재난 API HTTP 오류: ${response.statusCode}',
      );
    }

    final responseText = utf8.decode(response.bodyBytes);

    print('[재난 API] request page=$pageNo');
    print('[재난 API STATUS] ${response.statusCode}');

    final decoded = jsonDecode(responseText);

    if (decoded is! Map<String, dynamic>) {
      throw Exception('재난 API 응답 형식 오류');
    }

    final header = decoded['header'];

    if (header is Map<String, dynamic>) {
      final resultCode = header['resultCode']?.toString();

      if (resultCode != '00') {
        throw Exception(
          '재난 API 오류: ${header['resultMsg']}',
        );
      }
    }

    return decoded;
  }
}
