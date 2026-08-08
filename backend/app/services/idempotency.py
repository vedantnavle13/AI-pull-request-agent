processed_deliveries = set()


def already_processed(delivery_id: str) -> bool:
    return delivery_id in processed_deliveries


def mark_processed(delivery_id: str):
    processed_deliveries.add(delivery_id)