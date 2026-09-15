import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:safehub_app/core/appliance_controls.dart';
import 'package:safehub_app/services/shortcut_store.dart';

void main() {
  test('시뮬레이션은 실제 허브 상태와 분리된다', () {
    final model = ApplianceControls();
    model.applyPreview('aircon', 'on');
    expect(model.preview['aircon'], true);
    expect(model.hubAirconPower, isNull);
    model.applyPreview('aircon', 'toggle');
    expect(model.preview['aircon'], false);
    model.applyPreview('curtain', 'on');
    expect(model.preview['curtain'], true);
  });
  test('학진이 명령 형식 수신 및 중복 수신은 멱등적이다', () {
    final model = ApplianceControls();
    const topic = 'safehub/control/livingroom/aircon/command';
    final data = {'source': 'sign_shortcut', 'action': 'set_power', 'power_on': true};
    expect(model.receiveCommand(topic, data), true);
    model.receiveCommand(topic, data);
    expect(model.hubAirconPower, true);
    expect(model.preview['aircon'], false);
    expect(model.receiveCommand(topic, {'action': 'set_power', 'power_on': 'true'}), false);
    expect(model.receiveCommand('safehub/csi/bathroom/event', data), false);
  });
  test('단축키 등록·수정·삭제와 JSON 계약', () {
    final model = ApplianceControls();
    const binding = SignBinding(sign: '에어컨', device: 'aircon', action: 'toggle');
    model.register(binding);
    expect(jsonDecode(binding.registrationPayload()), {
      'operation': 'register', 'sign': '에어컨', 'room': 'livingroom',
      'device': 'aircon', 'action': 'toggle',
    });
    expect(jsonDecode(binding.removalPayload()), {'operation': 'remove', 'sign': '에어컨'});
    model.simulateSign(' 에어컨 ');
    expect(model.preview['aircon'], true);
    model.simulateSign('등록 안 됨');
    expect(model.preview['aircon'], true);
    model.register(const SignBinding(sign: '에어컨', device: 'light', action: 'on'));
    expect(model.bindings.length, 1);
    expect(model.bindings['에어컨']!.hubSupported, false);
    model.bindings.remove('에어컨');
    expect(model.bindings, isEmpty);
  });
  test('손상된 저장 데이터가 기존 목록을 부분적으로 바꾸지 않는다', () {
    final model = ApplianceControls();
    model.register(const SignBinding(sign: '에어컨', device: 'aircon', action: 'toggle'));
    final source = model.encode();
    final restored = ApplianceControls()..restore(source);
    expect(restored.encode(), source);
    expect(() => restored.restore('[{"sign":123}]'), throwsFormatException);
    expect(restored.encode(), source);
    expect(() => model.register(const SignBinding(sign: '', device: 'aircon', action: 'toggle')),
      throwsFormatException);
    expect(() => model.applyPreview('heater', 'on'), throwsArgumentError);
  });
  test('앱 저장소에서 재시작 후 단축키 복원', () async {
    final dir = await Directory.systemTemp.createTemp('safehub-shortcut-test-');
    addTearDown(() => dir.delete(recursive: true));
    final store = ShortcutStore(File('${dir.path}/shortcuts/bindings.json'));
    expect(await store.read(), isNull);
    final model = ApplianceControls()
      ..register(const SignBinding(sign: '에어컨', device: 'aircon', action: 'toggle'));
    await store.write(model.encode());
    final restarted = ApplianceControls()..restore((await store.read())!);
    expect(restarted.bindings['에어컨']!.hubSupported, true);
  });
}
