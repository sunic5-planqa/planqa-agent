# NxEF × Cafe24 연동 기술 스펙
**버전**: v1.0
**작성일**: 2024-02-15
**작성자**: 서비스기획팀 (개발팀 협의 기반)
**상태**: 검토 중

---

## 1. 개요

NxEF 어드민과 Cafe24 쇼핑몰 간의 데이터 연동 방식을 정의한다. 입고 어드민에서 상품이 등록되면 Cafe24에 자동으로 상품이 등록되어야 하며, Cafe24에서 주문이 발생하면 NxEF 어드민 주문 현황에도 반영되어야 한다.

---

## 2. 연동 범위

| 연동 항목 | 방향 | 방식 |
|---------|------|------|
| 상품 등록 | NxEF → Cafe24 | Cafe24 Open API 호출 |
| 주문 현황 동기화 | Cafe24 → NxEF | Cafe24 API |
| 주문 상태 변경 (배송 처리 등) | NxEF → Cafe24 | Cafe24 Open API 호출 |
| 재고 소진 처리 (품절) | Cafe24 → NxEF | Cafe24 API |

---

## 3. Cafe24 Open API 활용 (NxEF → Cafe24)

### 3-1. 상품 등록 API

- **Endpoint**: `POST /api/v2/admin/products`
- **인증**: OAuth 2.0 (Access Token 방식)
- **호출 시점**: 입고 어드민에서 카드가 '입금 완료' 스테이지로 이동하는 순간
- **전달 데이터**:

```json
{
  "product_name": "Nike Dunk Low Black _20397",
  "price": 0,
  "supply_price": 215000,
  "display": "T",
  "selling": "T",
  "category_no": 24,
  "options": [
    {
      "option_name": "사이즈",
      "option_value": "260"
    }
  ]
}
```

- **판매가(`price`)**: 입고 시점에 0으로 등록. 운영자가 이후 Cafe24 어드민에서 수동 설정.

### 3-2. 주문 상태 변경 API

- **Endpoint**: `PUT /api/v2/admin/orders/{order_id}/status`
- **호출 시점**: NxEF 어드민에서 배송 처리 버튼 클릭 시

---

## 4. Cafe24 이벤트 수신 (Cafe24 → NxEF)

Cafe24에서 주문, 결제, 재고 변경 등 이벤트가 발생할 때 NxEF 어드민에 실시간으로 반영되어야 한다.

### 4-1. 주문 발생 시 NxEF 어드민 반영

- Cafe24의 새 주문이 발생할 때마다 **Cafe24 API**를 통해 NxEF 어드민 주문 현황 화면에 실시간으로 반영된다.
- Cafe24 측에서 주문 이벤트가 발생하면 NxEF 서버의 지정된 엔드포인트로 데이터가 자동 전송되는 방식을 사용한다.
- NxEF 서버에서는 수신된 데이터를 파싱하여 주문 DB에 저장한다.

### 4-2. 재고 소진(품절) 시 처리

- Cafe24에서 특정 상품의 재고가 0이 되는 이벤트 발생 시, **Cafe24 API**를 통해 NxEF 어드민에 품절 상태가 전달된다.
- NxEF 어드민 상품 목록에서 해당 상품의 상태를 '품절'로 자동 업데이트.

---

## 5. 인증 관리

- Cafe24 Open API 사용을 위한 OAuth 2.0 Access Token은 만료 전 자동 갱신 처리 필요
- Token 갱신 실패 시 슬랙 #개발알림 채널에 알림 발송

---

## 6. 오류 처리

- Cafe24 API 호출 실패 시(타임아웃, 인증 오류 등) 어드민 화면에 오류 메시지 표시
- 실패 건은 재시도 큐에 적재하여 5분 후 1회 재시도
- 재시도 실패 시 슬랙 #개발알림 채널에 알림 발송

---

## 7. 관련 문서

- 입고 어드민 PRD (DOC-008)
- Cafe24 Open API 공식 문서
