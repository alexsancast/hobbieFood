/** @odoo-module **/

import { MessagingMenu } from "@mail/core/public_web/messaging_menu";
import { patch } from "@web/core/utils/patch";

// Replace the MessagingMenu template with an empty one to hide the systray icon
patch(MessagingMenu.prototype, {
    setup() {
        // Skip the original setup to prevent any systray rendering
    },
});

// Override the template to render nothing
MessagingMenu.template = "mail.HideDiscuss";
