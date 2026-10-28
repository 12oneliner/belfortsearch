-- Миграция 002: ссылка на сайт из карточки источника (ТЗ п.9).
-- Отличается от card_url: card_url — карточка в каталоге, website_url — заявленный сайт.

ALTER TABLE companies ADD COLUMN website_url TEXT;
