import 'dart:convert';

/// UI preview state is separate from the hub's last command (not hardware feedback).
class ApplianceControls {
  static const devices = {'aircon': '에어컨', 'light': '조명', 'curtain': '커튼'};
  static const actions = {'on': '켜기', 'off': '끄기', 'toggle': '켜기/끄기 전환'};
  final Map<String, bool> preview = {for (final id in devices.keys) id: false};
  bool? hubAirconPower;
  DateTime? hubCommandAt;
  final Map<String, SignBinding> bindings = {};

  void applyPreview(String device, String action) {
    if (!devices.containsKey(device) || !actions.containsKey(action)) {
      throw ArgumentError('지원하지 않는 기기 또는 동작');
    }
    preview[device] = action == 'toggle' ? !preview[device]! : action == 'on';
  }

  /// Idempotent absolute state: duplicate MQTT delivery never toggles twice.
  bool receiveCommand(String topic, Map<String, dynamic> data) {
    if (topic != 'safehub/control/livingroom/aircon/command' ||
        data['action'] != 'set_power' || data['power_on'] is! bool) return false;
    hubAirconPower = data['power_on'] as bool;
    hubCommandAt = DateTime.now();
    return true;
  }

  void register(SignBinding binding) {
    binding.validate();
    bindings[binding.sign] = binding;
  }

  void simulateSign(String sign) {
    final binding = bindings[sign.trim()];
    if (binding != null) applyPreview(binding.device, binding.action);
  }

  String encode() => jsonEncode(bindings.values.map((b) => b.toJson()).toList());

  void restore(String source) {
    final data = jsonDecode(source);
    if (data is! List) throw const FormatException('단축키 목록 형식 오류');
    final restored = <String, SignBinding>{};
    for (final item in data) {
      if (item is! Map<String, dynamic>) throw const FormatException('단축키 형식 오류');
      final binding = SignBinding.fromJson(item);
      binding.validate();
      restored[binding.sign] = binding;
    }
    bindings..clear()..addAll(restored);
  }
}

class SignBinding {
  final String sign;
  final String room;
  final String device;
  final String action;
  const SignBinding({required this.sign, this.room = 'livingroom',
    required this.device, required this.action});

  factory SignBinding.fromJson(Map<String, dynamic> data) {
    if (['sign', 'room', 'device', 'action'].any((k) => data[k] is! String)) {
      throw const FormatException('단축키 필드는 문자열이어야 합니다');
    }
    return SignBinding(sign: (data['sign'] as String).trim(),
      room: data['room'] as String, device: data['device'] as String,
      action: data['action'] as String);
  }

  bool get hubSupported => room == 'livingroom' && device == 'aircon' && action == 'toggle';
  void validate() {
    if (sign.trim().isEmpty || sign != sign.trim() || room != 'livingroom' ||
        !ApplianceControls.devices.containsKey(device) ||
        !ApplianceControls.actions.containsKey(action)) {
      throw const FormatException('수어·공간·기기·동작을 확인하세요');
    }
  }

  Map<String, dynamic> toJson() => {'sign': sign, 'room': room, 'device': device, 'action': action};
  String registrationPayload() => jsonEncode({'operation': 'register', ...toJson()});
  String removalPayload() => jsonEncode({'operation': 'remove', 'sign': sign});
}
