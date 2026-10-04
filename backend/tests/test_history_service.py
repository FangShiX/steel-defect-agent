"""检测记录与统计服务测试：JSON 读写、用户隔离、分页、统计聚合"""
from datetime import datetime, timedelta
from app.entity.db_models import User, DetectionScene
from app.services.history_service import history_service


def _make_user(db, username):
    user = User(username=username, email=f"{username}@example.com", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_scene(db):
    scene = DetectionScene(
        name="steel_surface_defect", display_name="钢铁表面缺陷检测",
        category="industry", class_names=["crazing", "scratches"],
    )
    db.add(scene)
    db.commit()
    db.refresh(scene)
    return scene


def test_create_and_complete_task_with_json_results(db_session):
    """验证 bbox / defect JSON 字段能正确写入和读出"""
    user = _make_user(db_session, "alice")
    scene = _make_scene(db_session)

    task = history_service.create_task(db_session, user.id, scene.id, task_type="single")
    assert task.status == "pending"

    history_service.mark_processing(db_session, task.id)
    history_service.add_results(db_session, task.id, [
        {"image_path": "/tmp/a.jpg", "class_name": "scratches", "class_id": 5,
         "confidence": 0.92, "bbox": [10.0, 20.0, 100.0, 200.0]},
    ])
    completed = history_service.mark_completed(db_session, task.id, total_images=1, total_objects=1, total_inference_time=120.5)

    assert completed.status == "completed"
    detail = history_service.get_task_detail(db_session, task.id, user.id)
    assert len(detail.results) == 1
    assert detail.results[0].bbox == [10.0, 20.0, 100.0, 200.0]  # JSON 列读出后类型/内容保持一致
    assert detail.results[0].class_name == "scratches"


def test_users_only_see_their_own_records(db_session):
    """用户隔离：非管理员看不到别人的检测记录"""
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    scene = _make_scene(db_session)

    history_service.create_task(db_session, alice.id, scene.id, task_type="single")
    history_service.create_task(db_session, bob.id, scene.id, task_type="single")

    alice_items, alice_total = history_service.list_tasks(db_session, user_id=alice.id, is_superuser=False)
    assert alice_total == 1
    assert all(t.user_id == alice.id for t in alice_items)

    admin_items, admin_total = history_service.list_tasks(db_session, user_id=alice.id, is_superuser=True)
    assert admin_total == 2  # 管理员能看到所有人的记录


def test_pagination(db_session):
    user = _make_user(db_session, "alice")
    scene = _make_scene(db_session)
    for _ in range(5):
        history_service.create_task(db_session, user.id, scene.id, task_type="single")

    page1, total = history_service.list_tasks(db_session, user_id=user.id, page=1, page_size=2)
    page2, _ = history_service.list_tasks(db_session, user_id=user.id, page=2, page_size=2)

    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert {t.id for t in page1}.isdisjoint({t.id for t in page2})


def test_statistics_matches_actual_data(db_session):
    """统计结果要跟数据库实际数据一致（任务文档步骤 9 的验收标准）"""
    user = _make_user(db_session, "alice")
    scene = _make_scene(db_session)

    t1 = history_service.create_task(db_session, user.id, scene.id, task_type="single")
    history_service.add_results(db_session, t1.id, [
        {"image_path": "/a.jpg", "class_name": "scratches", "class_id": 5, "confidence": 0.9, "bbox": [0, 0, 1, 1]},
        {"image_path": "/a.jpg", "class_name": "crazing", "class_id": 0, "confidence": 0.8, "bbox": [0, 0, 1, 1]},
    ])
    history_service.mark_completed(db_session, t1.id, total_images=1, total_objects=2, total_inference_time=100)

    stats = history_service.get_statistics(db_session, user_id=user.id)
    assert stats["total_tasks"] == 1
    assert stats["total_images"] == 1
    assert stats["total_objects"] == 2
    assert stats["class_distribution"] == {"scratches": 1, "crazing": 1}
    assert stats["daily_inference_time"][-1]["min"] == 100
    assert stats["daily_inference_time"][-1]["max"] == 100
    assert stats["daily_inference_time"][-1]["avg"] == 100


def test_daily_inference_time_includes_completed_tasks_without_results(db_session):
    user = _make_user(db_session, "alice")
    scene = _make_scene(db_session)

    task = history_service.create_task(db_session, user.id, scene.id, task_type="single")
    history_service.mark_completed(
        db_session, task.id, total_images=1, total_objects=0, total_inference_time=42.5
    )

    stats = history_service.get_statistics(db_session, user_id=user.id)
    assert stats["daily_inference_time"][-1] == {
        "date": stats["daily_inference_time"][-1]["date"],
        "min": 42.5,
        "max": 42.5,
        "avg": 42.5,
    }


def test_statistics_uses_the_same_period_and_status_contract(db_session):
    """默认看板只统计周期内完成任务，避免列表与统计口径不一致。"""
    user = _make_user(db_session, "alice")
    scene = _make_scene(db_session)

    completed = history_service.create_task(db_session, user.id, scene.id, task_type="single")
    history_service.add_results(db_session, completed.id, [
        {"image_path": "/recent.jpg", "class_name": "scratches", "class_id": 5, "confidence": 0.9, "bbox": [0, 0, 1, 1]},
    ])
    history_service.mark_completed(db_session, completed.id, total_images=1, total_objects=1, total_inference_time=20)

    failed = history_service.create_task(db_session, user.id, scene.id, task_type="single")
    history_service.add_results(db_session, failed.id, [
        {"image_path": "/failed.jpg", "class_name": "crazing", "class_id": 0, "confidence": 0.8, "bbox": [0, 0, 1, 1]},
    ])
    history_service.mark_failed(db_session, failed.id, "inference failed")

    old = history_service.create_task(db_session, user.id, scene.id, task_type="single")
    history_service.mark_completed(db_session, old.id, total_images=9, total_objects=9, total_inference_time=99)
    old.created_at = datetime.now() - timedelta(days=60)
    db_session.commit()

    stats = history_service.get_statistics(db_session, user_id=user.id, days=30)
    assert stats["total_tasks"] == 1
    assert stats["total_images"] == 1
    assert stats["class_distribution"] == {"scratches": 1}

    failed_stats = history_service.get_statistics(db_session, user_id=user.id, days=30, status="failed")
    assert failed_stats["total_tasks"] == 1
    assert failed_stats["class_distribution"] == {"crazing": 1}


def test_delete_task_moves_task_and_results_to_recycle_bin(db_session):
    user = _make_user(db_session, "alice")
    scene = _make_scene(db_session)
    task = history_service.create_task(db_session, user.id, scene.id, task_type="single")
    history_service.add_results(db_session, task.id, [
        {"image_path": "/a.jpg", "class_name": "scratches", "class_id": 5, "confidence": 0.9, "bbox": [0, 0, 1, 1]},
    ])

    recycled = history_service.delete_task(db_session, task.id, user.id)

    items, total = history_service.list_tasks(db_session, user_id=user.id)
    assert total == 0
    assert recycled.deletion_status == "trashed"
    assert len(recycled.results) == 1
