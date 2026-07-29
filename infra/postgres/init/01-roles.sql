-- Инициализация ролей доверенного контура (ТЗ, SR-8, FR-12).
-- Роль medviz_audit получает права на audit_log в миграции 0002 (после создания таблицы).
-- Здесь создаётся сама роль на случай, если приложение подключается ею отдельно.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'medviz_audit') THEN
        CREATE ROLE medviz_audit LOGIN PASSWORD 'change_me_audit';
    END IF;
END
$$;
