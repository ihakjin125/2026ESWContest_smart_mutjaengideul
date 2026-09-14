import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';

class DisasterService {
  static const int _rowsPerPage = 20;

  Future<Map<String, dynamic>?> fetchLatest() async {
    final firstResponse = await _request(pageNo: 1);
    final candidates = <dynamic>[
      ..._extractBody(firstResponse),
    ];

    final totalCount = _parseNumber(firstResponse['totalCount']);
    final lastPage = totalCount <= 0 ? 1 : (totalCount / _rowsPerPage).ceil();

    // API 정렬 방향이 바뀌어도 대응하도록 첫 페이지와 마지막 페이지를 비교한다.
    if (lastPage > 1) {
      final lastResponse = await _request(pageNo: lastPage);
      candidates.addAll(_extractBody(lastResponse));
    }

    return selectLatest(candidates);
  }

  static List<dynamic> _extractBody(Map<String, dynamic> response) {
    final body = response['body'];

    if (body is! List) {
      return const [];
    }

    return body;
  }

  static String? identifierOf(Map<String, dynamic> disaster) {
    final value = disaster['SN'];

    if (value == null) {
      return null;
    }

    final identifier = value.toString().trim();
    return identifier.isEmpty ? null : identifier;
  }

  static Map<String, dynamic>? selectLatest(List<dynamic> items) {
    Map<String, dynamic>? latest;

    for (final item in items) {
      if (item is! Map) {
        continue;
      }

      final candidate = Map<String, dynamic>.from(item);

      if (latest == null || _compareDisasters(candidate, latest) > 0) {
        latest = candidate;
      }
    }

    return latest;
  }

  static int _compareDisasters(
    Map<String, dynamic> left,
    Map<String, dynamic> right,
  ) {
    final dateComparison =
        _dateKey(left['CRT_DT']).compareTo(_dateKey(right['CRT_DT']));

    if (dateComparison != 0) {
      return dateComparison;
    }

    return _parseNumber(left['SN']).compareTo(_parseNumber(right['SN']));
  }

  static String _dateKey(dynamic value) {
    return value?.toString().replaceAll(RegExp(r'[^0-9]'), '') ?? '';
  }

  static int _parseNumber(dynamic value) {
    if (value is num) {
      return value.toInt();
    }

    return int.tryParse(value?.toString().trim() ?? '') ?? -1;
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
