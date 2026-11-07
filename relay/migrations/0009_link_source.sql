-- Where a link came from: "invitation" (a location redeemed an invitation) or "admin" (the circle admin set it in the matrix).
ALTER TABLE links ADD COLUMN source TEXT NOT NULL DEFAULT 'invitation';
