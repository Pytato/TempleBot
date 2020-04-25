import quart.flask_patch

from flask_wtf import FlaskForm, RecaptchaField
from wtforms import validators
from discord.ext import commands
from quart import Quart, render_template, Response, g

import discord

import logging
import asyncio
import os
import uuid

from quart import Quart, Response, abort
import hypercorn.asyncio


class WebVerificationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("GCHQBot.Verification")
        self.db_client = None
        self.has_called_webserver = False
        self.captcha_keys = self.bot.recaptcha_keypair

    @commands.command()
    async def test_add_member(self, ctx):
        self.logger.debug("Test member command called")
        await self.__on_member_join_internal(ctx.author, force_remind=True)

    async def __on_member_join_internal(self, member, force_remind=False):
        db = self.db_client.gchqbot
        collection = db.members
        member_record = await collection.find_one(
            {"user_id": member.id, "guild_id": member.guild.id})
        self.logger.debug(f"Member record found: {member_record}")
        remind_verification = True
        member_uuid = None
        if member_record is None:
            member_uuid = uuid.uuid4()
            member_record = {
                "uuid": str(member_uuid),
                "user_id": member.id,
                "guild_id": member.guild.id,
                "roles": [],
                "verified": False
            }
            await collection.insert_one(member_record)
        elif member_record.verified is False:
            member_uuid = member_record.uuid
        else:
            remind_verification = False

        if remind_verification or force_remind:
            await member.send(f"You are yet to verify on {member.guild.name}. To do so, please visit the "
                              f"following URL: {self.bot.verification_domain}/{member_uuid}")
        else:
            await self.__repatriate_member(member, member_record)

    async def verify_member(self, member_uuid):
        self.logger.info(f"UUID {member_uuid} passed the verification test.")
        await self.db_client.gchqbot.members.update_one(
            {"uuid": str(member_uuid)},
            {"$set": {"verified": True}}
        )

    @commands.Cog.listener()
    async def on_member_join(self, member):
        self.logger.info(f"{member} joined the guild: {member.guild}")
        await self.__on_member_join_internal(member)

    async def __repatriate_member(self, member, record):
        """Internal function used to return roles owned by a member before they left the server back to them
        after they rejoin, based on the most recent backup in the Database."""
        self.logger.info(f"Repatriating member {member} on {member.guild}")

    @commands.Cog.listener()
    async def on_ready(self):
        if self.bot.get_cog("DBSetup").db_client is None:
            await asyncio.sleep(0.25)
        self.db_client = self.bot.get_cog("DBSetup").db_client

        if not self.has_called_webserver:
            if self.db_client is None:
                await asyncio.sleep(0.25)
            await self.run_server()
            self.has_called_webserver = True

    async def run_server(self):
        app = Quart(__name__)
        db_client = self.db_client
        event_loop = asyncio.get_event_loop()
        config_data = self.bot.config_data
        app.config["SECRET_KEY"] = config_data["base"]["webserver_secret_session_key"]
        app.config["RECAPTCHA_USE_SSL"] = False
        app.config['RECAPTCHA_PUBLIC_KEY'] = config_data["captcha"]["sitekey"]
        app.config['RECAPTCHA_PRIVATE_KEY'] = config_data["captcha"]["privatekey"]
        app.config['RECAPTCHA_DATA_ATTRS'] = {"theme": 'dark'}
        configuration = hypercorn.Config().from_mapping({
            "host": "localhost",
            "port": 5000
        })
        event_loop.create_task(hypercorn.asyncio.serve(app, configuration))

        class VerifyForm(FlaskForm):
            recaptcha = RecaptchaField()

        @app.errorhandler(404)
        async def err_404_handler(error):
            return await render_template("not_found.html")

        @app.route("/<uuid:verif_id>", methods=["GET", "POST"])
        async def handle_verification(verif_id):
            verif_form = VerifyForm()

            if verif_form.validate_on_submit():
                await self.verify_member(str(verif_id))
                return await render_template("verification_success.html")

            if db_client is None:
                return Response("Error occurred while fetching results, try again.", 503)
            members_collection = db_client.gchqbot.members
            member_record = await members_collection.find_one({"uuid": str(verif_id)})
            if member_record is None or member_record["verified"] is True:
                abort(404)

            # Now we have a valid user record, let's use our verification page template to help them verify
            return await render_template("verification.html", form=verif_form, verif_uuid=verif_id)


def setup(bot):
    bot.add_cog(WebVerificationCog(bot))
