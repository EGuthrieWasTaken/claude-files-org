;;; driver.el --- apply one org command in batch mode, for byte-for-byte comparison  -*- lexical-binding: t; -*-
;;
;; Environment:
;;   ORACLE_FILE  absolute path of the org file to edit (it is saved in place)
;;   ORACLE_OP    set-state reschedule set-deadline add-note set-tags set-effort add-item archive
;;   ORACLE_ARGS  JSON object with the arguments of the op (see `oracle--run')
;;   ORACLE_NOW   frozen local time, "YYYY-MM-DD HH:MM"
;;   TZ           timezone (set by the caller)
;;   HOME         the served folder is $HOME/.emacs.d, as Emacs sees it in production

(when (getenv "ORACLE_ELN")
  ;; keep native-compilation trampolines out of the served folder
  (setq native-comp-eln-load-path (list (getenv "ORACLE_ELN"))))
(require 'org)
(require 'org-archive)
(require 'org-capture)
(require 'cl-lib)
(require 'json)

;; Ethan's org settings (config.org, "Org Agenda").
(setq org-todo-keywords '((sequence "TODO(t)" "STARTED(s)" "WAIT(w@)" "|" "DONE(d)" "CANCELLED(c@)"))
      org-log-done 'time
      org-log-reschedule 'time
      org-log-redeadline 'time
      org-log-into-drawer t
      org-tags-column -77
      org-adapt-indentation nil
      org-archive-location "~/.emacs.d/org-projects/archive/%s_archive::"
      org-archive-subtree-save-file-p nil
      org-tag-alist '(("stephen") ("jwa") ("research") ("coursework") ("admin") (:startgrouptag) ("personal") (:grouptags) ("blog") (:endgrouptag))
      make-backup-files nil
      auto-save-default nil
      create-lockfiles nil)

(defvar oracle--frozen nil)

(defun oracle--install-clock (now)
  "Freeze the clock at NOW (local time string)."
  (let ((frozen (encode-time (parse-time-string (concat now ":00")))))
    (setq oracle--frozen frozen)
    (advice-add 'current-time :override (lambda () oracle--frozen))
    (advice-add 'format-time-string :around
                (lambda (orig fmt &optional time zone)
                  (funcall orig fmt (or time oracle--frozen) zone)))))

(defun oracle--arg (args key &optional default)
  (let ((cell (assoc key args)))
    (if cell (cdr cell) default)))

(defun oracle--goto (path nth)
  "Move to the NTH heading whose normalized outline path is PATH (a \"/\" joined string)."
  (goto-char (point-min))
  (let ((hits 0) found)
    (while (and (not found) (re-search-forward org-heading-regexp nil t))
      (beginning-of-line)
      (let ((title (org-get-heading t t t t)))
        (when (equal (string-join (append (org-get-outline-path) (list title)) "/") path)
          (if (= hits nth) (setq found (point)) (setq hits (1+ hits)))))
      (end-of-line))
    (unless found (error "heading not found: %s #%d" path nth))
    (goto-char found)
    (beginning-of-line)))

(defun oracle--run-post-command ()
  "Batch mode never runs `post-command-hook', where org queues its log notes."
  (run-hooks 'post-command-hook))

(defun oracle--finish-note (text)
  "Complete the pending org log note with TEXT (batch stand-in for typing in the note buffer)."
  (let ((buf (get-buffer "*Org Note*")))
    (unless buf (error "no note buffer was opened"))
    (with-current-buffer buf
      (erase-buffer)
      (insert text)
      (let ((org-note-abort nil)) (org-store-log-note)))))

(defun oracle--op-set-state (args)
  (let ((state (oracle--arg args 'state)) (note (oracle--arg args 'note)))
    (org-todo state)
    (oracle--run-post-command)
    (when (get-buffer "*Org Note*") (oracle--finish-note (or note "")))))

(defun oracle--date-arg (args)
  (let ((d (oracle--arg args 'date)) (tm (oracle--arg args 'time)))
    (if tm (concat d " " tm) d)))

(defun oracle--op-planning (fn args remove-prefix)
  (let ((note (oracle--arg args 'note)) (remove (oracle--arg args 'remove)))
    (when note (cond ((eq fn 'org-schedule) (setq org-log-reschedule 'note))
                     (t (setq org-log-redeadline 'note))))
    (if (and remove (not (eq remove :json-false)))
        (funcall fn remove-prefix)
      (funcall fn nil (oracle--date-arg args)))
    (oracle--run-post-command)
    (when (get-buffer "*Org Note*") (oracle--finish-note (or note "")))))

(defun oracle--op-add-note (args)
  (org-add-note)
  (oracle--run-post-command)
  (oracle--finish-note (oracle--arg args 'note)))

(defun oracle--op-set-tags (args)
  (org-set-tags (append (oracle--arg args 'tags) nil)))

(defun oracle--op-set-effort (args)
  (let ((v (oracle--arg args 'value)))
    (if v (org-set-effort nil v) (org-delete-property "Effort"))))

(defun oracle--op-archive (_args)
  (org-archive-subtree)
  ;; save the archive buffer ourselves (save-file-p is off so the order is explicit)
  (let ((archive (expand-file-name (format "~/.emacs.d/org-projects/archive/%s_archive"
                                           (file-name-nondirectory (buffer-file-name))))))
    (let ((buf (find-buffer-visiting archive)))
      (when buf (with-current-buffer buf (save-buffer))))))

(defun oracle--op-add-item (args)
  "Capture with a template built from ARGS, like Ethan's `t' template."
  (let* ((title (oracle--arg args 'title))
         (parent (oracle--arg args 'parent "Tasks"))
         (tags (append (oracle--arg args 'tags) nil))
         (planning (oracle--arg args 'planning))
         (effort (oracle--arg args 'effort))
         (body (oracle--arg args 'body))
         (head (concat "* TODO " title
                       (if tags (concat " :" (string-join tags ":") ":") "")))
         (tpl (concat head "\n"
                      (if planning (concat planning "\n") "")
                      ":PROPERTIES:\n:CREATED:  %U\n"
                      (if effort (concat ":Effort:   " effort "\n") "")
                      ":END:\n"
                      (if body (concat body "\n") "")))
         (org-capture-templates
          `(("t" "Task" entry (file+olp ,(buffer-file-name) ,@(split-string parent "/")) ,tpl :immediate-finish t))))
    (org-capture nil "t")))

(defun oracle--run ()
  (let* ((file (getenv "ORACLE_FILE"))
         (op (getenv "ORACLE_OP"))
         (now (getenv "ORACLE_NOW"))
         (args (let ((json-object-type 'alist) (json-array-type 'list) (json-key-type 'symbol))
                 (json-read-from-string (or (getenv "ORACLE_ARGS") "{}"))))
         (path (oracle--arg args 'path))
         (nth (oracle--arg args 'nth 0)))
    (oracle--install-clock now)
    (find-file file)
    (org-mode)
    (when path (oracle--goto path nth))
    (cond
     ((equal op "set-state") (oracle--op-set-state args))
     ((equal op "reschedule") (oracle--op-planning 'org-schedule args '(4)))
     ((equal op "set-deadline") (oracle--op-planning 'org-deadline args '(4)))
     ((equal op "add-note") (oracle--op-add-note args))
     ((equal op "set-tags") (oracle--op-set-tags args))
     ((equal op "set-effort") (oracle--op-set-effort args))
     ((equal op "archive") (oracle--op-archive args))
     ((equal op "add-item") (oracle--op-add-item args))
     (t (error "unknown op %s" op)))
    (save-buffer)
    (princ "OK\n")))

(oracle--run)
