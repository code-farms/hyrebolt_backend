-- DropIndex
DROP INDEX "Job_sourceId_idx";

-- CreateIndex
CREATE INDEX "Application_userId_updatedAt_idx" ON "Application"("userId", "updatedAt");

-- CreateIndex
CREATE INDEX "ApplicationEvent_status_occurredAt_idx" ON "ApplicationEvent"("status", "occurredAt");

-- CreateIndex
CREATE INDEX "Job_deletedAt_createdAt_idx" ON "Job"("deletedAt", "createdAt");

-- CreateIndex
CREATE INDEX "JobMatch_updatedAt_idx" ON "JobMatch"("updatedAt");

-- CreateIndex
CREATE INDEX "Notification_createdAt_idx" ON "Notification"("createdAt");

-- CreateIndex
CREATE INDEX "Notification_userId_channel_createdAt_idx" ON "Notification"("userId", "channel", "createdAt");

-- CreateIndex
CREATE INDEX "Notification_userId_channel_readAt_idx" ON "Notification"("userId", "channel", "readAt");

-- CreateIndex
CREATE INDEX "SearchRun_trigger_createdAt_idx" ON "SearchRun"("trigger", "createdAt");
