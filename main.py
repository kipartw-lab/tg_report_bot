def main():
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    # сообщения
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # /schedule
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CallbackQueryHandler(schedule_callback))

    jq = application.job_queue

    # Выводы
    jq.run_daily(conclusions_reminder_1230, time(12, 30, tzinfo=TZ))
    jq.run_daily(conclusions_reminder_1300, time(13, 0, tzinfo=TZ))
    jq.run_daily(conclusions_admin_1310, time(13, 10, tzinfo=TZ))

    # Срезы 16:00
    jq.run_daily(slices_reminder_1600, time(16, 0, tzinfo=TZ))
    jq.run_daily(slices_reminder_1630, time(16, 30, tzinfo=TZ))
    jq.run_daily(slices_admin_1640, time(16, 40, tzinfo=TZ))

    # Тимур
    jq.run_daily(timur_reminder_1730, time(17, 30, tzinfo=TZ))
    jq.run_daily(timur_reminder_1750, time(17, 50, tzinfo=TZ))
    jq.run_daily(timur_admin_1800, time(18, 0, tzinfo=TZ))

    # Отчёты
    jq.run_daily(reports_reminder_1900, time(19, 0, tzinfo=TZ))
    jq.run_daily(reports_reminder_2100, time(21, 0, tzinfo=TZ))
    jq.run_daily(reports_warning_2240, time(22, 40, tzinfo=TZ))
    jq.run_daily(reports_summary_2300, time(23, 0, tzinfo=TZ))

    # Директор
    jq.run_daily(director_reports_0500, time(5, 0, tzinfo=TZ))
    jq.run_daily(director_slices_1800, time(18, 0, tzinfo=TZ))

    logger.info("Bot started (PTB v20)")
    application.run_polling(close_loop=False)


if __name__ == "__main__":
    clear_old(days=2)
    save_data()
    main()
