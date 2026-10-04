-- Инициализация ролей доверенного контура (ТЗ, SR-8, FR-12).
-- Роль medviz_audit получает права на audit_log в миграции 0002 (после создания таблицы).
-- Здесь создаётся сама роль. Пароля нет: приложение этой ролью не входит, а роль с
-- известным паролем дала бы вход в базу (миграция 0019 снимает пароль и на старых базах).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'medviz_audit') THEN
        CREATE ROLE medviz_audit LOGIN;
    END IF;
END
$$;
